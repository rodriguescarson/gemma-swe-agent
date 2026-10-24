"""One-time AWS setup for the kit: the S3 bucket and the instance profile the machines use to reach it. Plan only, unless --yes.

    python aws/account_setup.py [--bucket NAME] [--yes]

Creates what is missing, and nothing else:
  - bucket (default gemma4-agent-<account id>) in us-east-1: public access blocked, SSE-S3, tagged Project=gemma4-agent;
  - IAM role + instance profile gemma4-agent-ec2: EC2 may assume it, and it may only list the bucket and get/put objects in
    it. No delete: a machine can never remove an artifact, and it holds no other AWS permission.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g4aws  # noqa: E402
from launch import PROFILE  # noqa: E402

TRUST = {"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]}


def bucket_policy_for_role(bucket):
    return {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": f"arn:aws:s3:::{bucket}"},
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
         "Resource": f"arn:aws:s3:::{bucket}/*"}]}


def plan(sess, bucket):
    from botocore.exceptions import ClientError
    s3, iam, todo = sess.client("s3"), sess.client("iam"), []
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("403", "AccessDenied"):
            raise SystemExit(f"bucket {bucket} exists but is not ours (403); pick another --bucket")
        todo.append("bucket")
    try:
        iam.get_role(RoleName=PROFILE)
    except ClientError:
        todo.append("role")
    try:
        prof = iam.get_instance_profile(InstanceProfileName=PROFILE)["InstanceProfile"]
        if not any(r["RoleName"] == PROFILE for r in prof.get("Roles", [])):
            todo.append("attach")
    except ClientError:
        todo += ["profile", "attach"]
    return todo


def apply(sess, bucket, todo):
    s3, iam = sess.client("s3"), sess.client("iam")
    tags = [{"Key": "Project", "Value": g4aws.PROJECT}]
    if "bucket" in todo:
        s3.create_bucket(Bucket=bucket)   # us-east-1 takes no LocationConstraint
        s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
        s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
        s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": tags})
    if "role" in todo:
        iam.create_role(RoleName=PROFILE, AssumeRolePolicyDocument=json.dumps(TRUST), Tags=tags,
                        Description="gemma4-agent EC2 machines: read/write the kit's S3 bucket, nothing else")
    iam.put_role_policy(RoleName=PROFILE, PolicyName="g4-s3", PolicyDocument=json.dumps(bucket_policy_for_role(bucket)))
    if "profile" in todo:
        iam.create_instance_profile(InstanceProfileName=PROFILE, Tags=tags)
    if "attach" in todo:
        iam.add_role_to_instance_profile(InstanceProfileName=PROFILE, RoleName=PROFILE)
        time.sleep(10)   # a fresh instance profile takes a few seconds before RunInstances accepts it


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bucket"); ap.add_argument("--yes", action="store_true", help="create what is missing")
    a = ap.parse_args(argv)
    sess = g4aws.session()
    bucket = a.bucket or f"gemma4-agent-{sess.client('sts').get_caller_identity()['Account']}"
    todo = plan(sess, bucket)
    print(f"bucket s3://{bucket}, instance profile {PROFILE}: " + (f"missing {todo}" if todo else "all present"))
    print("role policy:", json.dumps(bucket_policy_for_role(bucket)))
    if not a.yes:
        print("nothing was created; add --yes to create what is missing" if todo else "nothing to do")
        return 0
    apply(sess, bucket, todo)
    left = plan(sess, bucket)
    print("done; still missing: " + (str(left) if left else "nothing"))
    print(f"runs: s3://{bucket}/runs/<id>/  shared: s3://{bucket}/shared/")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
