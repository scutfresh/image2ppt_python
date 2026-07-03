from rembg import remove
	
# 打开要处理的图片
##给出当前目录下文件夹路径，遍历处理所有文件夹内的图片
import os
input_folder = r'projects\20260604_qwen3_6_35b_a3b_and_z_image_turbo_2\component_images'
output_folder = r'projects\20260604_qwen3_6_35b_a3b_and_z_image_turbo_2\output_images'
for filename in os.listdir(input_folder):
    if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename)
        with open(input_path, 'rb') as input_file:
            input_image = input_file.read()
        # 移除背景
        output_image = remove(input_image)
        # 保存结果
        with open(output_path, 'wb') as output_file:
            output_file.write(output_image)
        print(f"背景已移除并保存为 {output_path}")

# with open(input_path, 'rb') as input_file:
# input_image = input_file.read()
	
# # 移除背景
# output_image = remove(input_image)
	
# # 保存结果
# with open(output_path, 'wb') as output_file:
# output_file.write(output_image)
	
# print(f"背景已移除并保存为 {output_path}")