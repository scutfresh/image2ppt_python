import os
import torch
import argparse
 
# ==========================================
# 0. 配置缓存 (保命操作，勿删)
# ==========================================
workspace_dir = "D:/Desktop/image2ppt/langchain"  # 修改为你自己的路径
os.makedirs(workspace_dir, exist_ok=True)
os.environ["MODELSCOPE_CACHE"] = workspace_dir
os.environ["HF_HOME"] = workspace_dir
 
from modelscope import ZImagePipeline
 
# ==========================================
# 1. 参数解析
# ==========================================
def parse_args():
    parser = argparse.ArgumentParser(description="Z-Image-Turbo CLI Tool")
    
    parser.add_argument(
        "--prompt", 
        type=str, 
        required=False,
        default="A cute cyberpunk cat, neon lights, 8k high definition",
        help="输入你的提示词"
    )
    
    parser.add_argument(
        "--output", 
        type=str, 
        default="result.png", 
        help="输出图片的文件名"
    )
 
    return parser.parse_args()
 
# ==========================================
# 2. 主逻辑
# ==========================================
if __name__ == "__main__":
    args = parse_args()
    
    print(f">>> 当前提示词: {args.prompt}")
    print(f">>> 输出文件名: {args.output}")
 
    print(">>> 正在加载模型...")
    pipe = ZImagePipeline.from_pretrained(
        "Tongyi-MAI/Z-Image-Turbo",
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=False,
    )
    pipe.to("cuda")
 
    print(">>> 开始生成...")
    try:
        image = pipe(
            prompt=args.prompt,
            height=1024,
            width=1024,
            num_inference_steps=9,
            guidance_scale=0.0,
            generator=torch.Generator("cuda").manual_seed(42),
        ).images[0]
 
        image.save(args.output)
        print(f"\n✅ 成功！图片已保存至: {os.path.abspath(args.output)}")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")