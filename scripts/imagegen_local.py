import requests
import base64

# 1. 请求地址（本地推理服务，记得替换ip+端口）
url = "http://192.168.210.128:8091/v1/chat/completions"

# 2. 请求头
headers = {"Content-Type": "application/json"}

# 3. 请求参数
data = {
    "messages": [
        {"role": "user", "content": "A beautiful landscape painting"}
    ],
    "extra_body": {
        "height": 1024,
        "width": 1024,
        "num_inference_steps": 50,
        "true_cfg_scale": 4.0,
        "seed": 42
    }
}

# 4. 发送 POST 请求
response = requests.post(url, json=data, headers=headers, timeout=300)
result = response.json()

# 5. 从返回结果里提取 base64 图片数据（去掉前缀 data:image/png;base64,）
image_base64 = result["choices"][0]["message"]["content"][0]["image_url"]["url"].split(",", 1)[1]

# 6. base64 解码并保存为图片
with open("output.png", "wb") as f:
    f.write(base64.b64decode(image_base64))

print("图片已保存：output.png")