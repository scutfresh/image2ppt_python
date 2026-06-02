# Image2PPT Langchain Workflow

本目录提供从位图输入到可编辑 PPTX 的自动化流程。核心入口为 `agent_workflow.py`。

## 快速开始

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 配置环境变量（见下文）

3. 运行

```bash
python agent_workflow.py --source /path/to/input.png
```

## 环境变量

### Vision (视觉分析)

- IMAGE2PPT_VISION_BASE_URL: OpenAI 兼容的 chat/completions 基础地址（必填）
- IMAGE2PPT_VISION_API_KEY: 视觉模型 API Key（可选）
- DASHSCOPE_API_KEY: 可作为 IMAGE2PPT_VISION_API_KEY 的后备（可选）
- IMAGE2PPT_VISION_MODEL: 视觉模型名称（默认: qwen-vl）

### ImageGen (图片生成)

- IMAGE2PPT_IMAGEGEN_BASE_URL: 图片生成 API 基础地址（必填）
- IMAGE2PPT_IMAGEGEN_API_KEY: 图片生成 API Key（可选）
- DASHSCOPE_API_KEY: 可作为 IMAGE2PPT_IMAGEGEN_API_KEY 的后备（可选）
- IMAGE2PPT_IMAGEGEN_MODEL: 图片生成模型名称（默认: z-image-turbo）


## 参数说明

入口脚本: `agent_workflow.py`

- --source (必填): 输入图片路径
- --date: 项目日期前缀，格式 YYYYMMDD
- --notes: 分析补充说明，作为提示词的一部分
- --test_vision: 只执行视觉分析和组件规划，输出诊断报告后退出
- --analysis-temperature: 视觉分析温度（默认: 0.2）
- --component-temperature: 组件规划与清单生成温度（默认: 0.2）
- --skip-verify: 跳过 PPTX 验证统计
- --vision-model: 覆盖视觉模型名称
- --vision-base-url: 覆盖视觉模型 API Base URL
- --imagegen-model: 覆盖图片生成模型名称
- --imagegen-base-url: 覆盖图片生成 API Base URL
- --imagegen-api-style: 图片生成 API 风格，openai 或 qwen
- --resume_analysis: 复用已有项目中的 analysis/component_plan
- --resume_imagegen: 复用已有项目中的资产，直接生成 manifest
- --resume_manifest: 复用已有 manifest，直接生成 PPTX

注意事项:
- resume_analysis、resume_imagegen、resume_manifest 互斥
- test_vision 不能与 resume_imagegen 或 resume_manifest 同时使用

## 输出结构

运行后在 projects/ 下按日期和模型生成项目目录，常见结构如下:

```
projects/20260602_qwen3_6_35b_a3b_and_qwen_image/
  original_inputs/        # 输入图片与提示词备份
  component_images/       # 生成的组件图片
  diagnostics/            # 分析与规划中间结果
    analysis.json
    component_plan.json
    asset_catalog.json
  manifest.json           # 最终清单
  output.pptx             # PPTX 输出
  summary.json            # 渲染摘要
  process_notes.md        # 运行记录
```

## 项目代码结构

- agent_workflow.py: 入口与流程编排
- prompts.py: 提示词
- openai_client.py: OpenAI 兼容对话客户端
- imagegen.py: 图片生成与后处理
- image2pptx.py: Manifest -> PPTX 渲染
- tools.py: 工具函数与 JSON 修复


## 命令示例


```bash
python agent_workflow.py --source D:\Desktop\南网\ppt图片.png --vision-model qwen3.6-plus --vision-base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --imagegen-model qwen-image --imagegen-base-url https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation --imagegen-api-style qwen 
```
