# Teacher licences and hosting terms (distillation plan, step 2; read 2026-10-24)

Rule being applied: the competition allows other models' outputs "in accordance with their model license terms", and the
result must not conflict with the winners' Apache-2.0 licence (forum 742807, comment 3530102, 2026-09-29). Our own rule
(research/distill.md section 2) clears Apache-2.0, MIT and modified MIT, and excludes GPT, Claude and Gemini outputs.
The hosting service's terms count too, not only the model licence (docs/PATH_TO_020.md C14).

## Model licences (read from each model's official Hugging Face repository)

| Model | Licence | Clause on outputs / derivatives | Verdict |
|---|---|---|---|
| Qwen3-Coder-480B-A35B-Instruct | Apache-2.0 (`Qwen/Qwen3-Coder-480B-A35B-Instruct/LICENSE`) | no restriction on outputs | CLEARED |
| Kimi K2.5 | Modified MIT (`moonshotai/Kimi-K2.5/LICENSE`) | MIT grant; the only change is a "Kimi K2.5" display requirement for products over 100M MAU or $20M monthly revenue | CLEARED |
| GLM-5.3 | "GLM-5.3 License", MIT-style (`zai-org/GLM-5.3/LICENSE`) | grant to "fine-tune ... and create derivative works"; extra clause only for model-as-a-service businesses with over $10B revenue (security review) | CLEARED |
| gpt-oss-120b | Apache-2.0 plus a one-line usage policy ("comply with all applicable law") (`openai/gpt-oss-120b`) | no restriction on outputs | CLEARED (earlier OpenRouter runs saw malformed tool-call JSON, 2026-10-03) |
| MiniMax M2.5 | MiniMax Model License (`MiniMaxAI/MiniMax-M2.5/LICENSE-MODEL`) | 2.b.i: distributing "a product or service that uses any of them, including another AI model" must ship this Agreement and notices; a Prohibited Uses Policy flows down | UNCLEAR: extra obligations on a derived model may conflict with the Apache-2.0-only winner licence. Not used |

## Hosting route

**Amazon Bedrock: BLOCKED for generating training data.** AWS Service Terms section 50.1 lists Amazon Bedrock as an "AI
Service", and section 50.5 begins "Except where permitted by the AI Service, you may not use an AI Service to generate
Content for the express purpose" of training an AI model (or developing a substantially similar one). Generating teacher
trajectories to fine-tune Gemma is that purpose. Section 50.12.1 makes third-party models "Third-Party Content" under their
own linked terms. Amazon's third-party model terms page says Qwen and DeepSeek serverless models on Bedrock "are sold by
AWS"; it shows no permission to use outputs for training. Without a written permission from AWS, no Bedrock teacher row is
used. The Bedrock proxy (router.BedrockEndpoint, commit 27abaab4) stays for uses that are not training data.

**Self-hosting open weights on EC2: CLEARED route.** EC2 is compute, not an AI Service under section 50, so only the model
licence applies. Limited by GPU quota and memory: a g6e.12xlarge (4x L40S, 192 GB) holds gpt-oss-120b or a ~30B coder;
Qwen3-Coder-480B or GLM-5.3 need 8x H100-class GPUs (P-family quota, about $98/h on demand).

**OpenRouter: per-provider check needed.** Earlier teacher collections used OpenRouter (Kimi, Qwen). Each serving
provider's terms would have to be read before rows count; spend would be cash, not AWS credits.
