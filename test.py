import subprocess

# 1. 在这里定义你要循环测试的 vision-model 列表
vision_models = [
    "qwen3.6-27b",
    "qwen3.6-35b-a3b",
    "qwen3.5-35b-a3b",
    "qwen3.5-27b",
    "qwen3.5-122b-a10b",
    "qwen3.5-397b-a17b",
    "qwen3-vl-32b-thinking",
    "qwen3-vl-32b-instruct",
    "qwen3-vl-30b-a3b-thinking",
    "qwen3-vl-30b-a3b-instruct",
    "qwen3-vl-8b-thinking",
    "qwen3-vl-8b-instruct",
    "qwen3-vl-235b-a22b-thinking",
    "qwen3-vl-235b-a22b-instruct",
    # "添加更多模型..."
]

# 2. 定义基础命令（不包含 --vision-model 参数）
base_command = [
    "python", "agent_workflow.py",
    "--source", r"D:\Desktop\南网\ppt图片.png", # 使用 r 前缀防止转义字符报错
    "--vision-base-url", "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "--imagegen-model", "qwen-image-2.0",
    "--imagegen-base-url", "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    "--imagegen-api-style", "qwen",
    "--test_vision"
]

def main():
    print(f"准备测试 {len(vision_models)} 个模型...\n")
    
    for model in vision_models:
        print("=" * 50)
        print(f"🚀 正在运行 Vision Model: {model}")
        print("=" * 50)
        
        # 复制基础命令并追加当前循环的模型参数
        command = base_command.copy()
        command.extend(["--vision-model", model])
        
        try:
            # 运行命令，保持输出打印在控制台上
            subprocess.run(command, check=True)
            print(f"\n✅ [成功] 模型 {model} 测试完成。\n")
        except subprocess.CalledProcessError as e:
            print(f"\n❌ [失败] 模型 {model} 运行报错退出了，退出码: {e.returncode}\n")
        except Exception as e:
            print(f"\n⚠️ [异常] 运行模型 {model} 时发生未知错误: {e}\n")

if __name__ == "__main__":
    main()