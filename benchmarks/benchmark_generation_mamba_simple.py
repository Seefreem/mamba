# Copyright (c) 2023, Tri Dao, Albert Gu.

'''
Example:
python benchmarks/benchmark_generation_mamba_simple.py --model-name "state-spaces/mamba-2.8b" 
--prompt "My cat wrote all this CUDA code for a new language model and" 
--topp 0.9 --temperature 0.7 --repetition-penalty 1.2

'''

import argparse
import time
import json

import torch
import torch.nn.functional as F

from einops import rearrange

from transformers import AutoTokenizer, AutoModelForCausalLM

from mamba_ssm.models.mixer_seq_simple import MambaLMHeadModel


parser = argparse.ArgumentParser(description="Generation benchmarking")
parser.add_argument("--model-name", type=str, default="state-spaces/mamba-130m")
parser.add_argument("--prompt", type=str, default=None)
parser.add_argument("--promptlen", type=int, default=100)
parser.add_argument("--genlen", type=int, default=100)
parser.add_argument("--temperature", type=float, default=1.0)
parser.add_argument("--topk", type=int, default=1)
parser.add_argument("--topp", type=float, default=1.0)
parser.add_argument("--minp", type=float, default=0.0)
parser.add_argument("--repetition-penalty", type=float, default=1.0)
parser.add_argument("--batch", type=int, default=1)
args = parser.parse_args()

repeats = 3
device = "cuda"
dtype = torch.float16

print(f"Loading model {args.model_name}")
is_mamba = args.model_name.startswith("state-spaces/mamba-")
if is_mamba:
    tokenizer = AutoTokenizer.from_pretrained("EleutherAI/gpt-neox-20b")
    model = MambaLMHeadModel.from_pretrained(args.model_name, device=device, dtype=dtype)
else:
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    model = AutoModelForCausalLM.from_pretrained(args.model_name, device_map={"": device}, torch_dtype=dtype)
model.eval()
print(f"Number of parameters: {sum(p.numel() for p in model.parameters() if p.requires_grad)}")

torch.random.manual_seed(0)
if args.prompt is None:
    input_ids = torch.randint(1, 1000, (args.batch, args.promptlen), dtype=torch.long, device="cuda")
    attn_mask = torch.ones_like(input_ids, dtype=torch.long, device="cuda")
else:
    tokens = tokenizer(args.prompt, return_tensors="pt")
    input_ids = tokens.input_ids.to(device=device)
    attn_mask = tokens.attention_mask.to(device=device)
max_length = input_ids.shape[1] + args.genlen

if is_mamba:
    fn = lambda: model.generate(
        input_ids=input_ids,
        max_length=max_length,
        cg=True,
        return_dict_in_generate=True,
        output_scores=True,
        enable_timing=False,
        temperature=args.temperature,
        top_k=args.topk,
        top_p=args.topp,
        min_p=args.minp,
        repetition_penalty=args.repetition_penalty,
    )
else:
    fn = lambda: model.generate(
        input_ids=input_ids,
        attention_mask=attn_mask,
        max_length=max_length,
        return_dict_in_generate=True,
        pad_token_id=tokenizer.eos_token_id,
        do_sample=True,
        temperature=args.temperature,
        top_k=args.topk,
        top_p=args.topp,
        repetition_penalty=args.repetition_penalty,
    )
out = fn() # 这一行是在执行 inference，执行结果存在out中。需要注意的是，输出是得解码的。输出也是ids。
if args.prompt is not None:
    print(tokenizer.batch_decode(out.sequences.tolist()))

# 下面的代码是为了计算decode的时间开销
torch.cuda.synchronize()
start = time.time()
for _ in range(repeats):
    fn()
torch.cuda.synchronize()
print(f"Prompt length: {len(input_ids[0])}, generation length: {len(out.sequences[0]) - len(input_ids[0])}")
print(f"{args.model_name} prompt processing + decoding time: {(time.time() - start) / repeats * 1000:.0f}ms")
