from PIL import Image, ImageFilter, ImageFile
import numpy as np
from typing import Tuple

# otsu算法生成二值图
async def otsu_threshold(image: ImageFile) -> ImageFile:
    # 将图像转换为灰度图
    gray_image = image.convert('L')
    # 模糊处理
    af_gray = gray_image.filter(ImageFilter.GaussianBlur(radius=2))
    # 将图像数据转为NumPy数组
    pixel_array = np.array(af_gray)
    
    # 计算直方图
    hist, bins = np.histogram(pixel_array.flatten(), bins=256, range=[0, 256])
    
    # 计算总像素数
    total_pixels = pixel_array.size
    
    # 初始化变量
    current_max, threshold = 0, 0
    sum_t, sum_f, weight_b, weight_f = 0, np.sum(np.arange(256) * hist), 0, 0
    
    for i in range(256):
        weight_b += hist[i]
        # 前景权重
        if weight_b == 0:
            continue
        
        # 背景权重
        weight_f = total_pixels - weight_b
        if weight_f == 0:
            break
            
        sum_t += i * hist[i]
        
        mean_b = sum_t / weight_b
        mean_f = (sum_f - sum_t) / weight_f
        
        # 计算类间方差
        between_variance = weight_b * weight_f * (mean_b - mean_f) ** 2
        
        # 找到最大类间方差对应的阈值
        if between_variance > current_max:
            current_max = between_variance
            threshold = i
    
    binarry_image = image.convert('L').point(lambda x: 255 if x > threshold else 0)
    return binarry_image

# Sobel算子边沿检测
# 效果不如Canny算子
async def Sobel_edge_detection(gray_image:ImageFile) -> ImageFile:
    # 定义Sobel算子的x和y方向核
    sobel_x = np.array([[1, 0, -1],
                         [2, 0, -2],
                         [1, 0, -1]])
    
    sobel_y = np.array([[1, 2, 1],
                         [0, 0, 0],
                         [-1, -2, -1]])
    
    # 应用Sobel算子
    img_array = np.array(gray_image)
    rows, cols = img_array.shape
    
    # 创建空数组来保存边缘检测结果
    output = np.zeros((rows, cols), dtype=np.float32)
    
    # 对图像进行卷积操作
    for i in range(1, rows-1):
        for j in range(1, cols-1):
            gx = np.sum(sobel_x * img_array[i-1:i+2, j-1:j+2])
            gy = np.sum(sobel_y * img_array[i-1:i+2, j-1:j+2])
            # 计算梯度幅值
            output[i, j] = np.sqrt(gx**2 + gy**2)
    
    # 归一化输出结果到0-255范围
    output = (output / output.max()) * 255
    return Image.fromarray(output.astype(np.uint8))

# 模板匹配
async def match_template(source_image:ImageFile, template_image:ImageFile) -> Tuple[tuple, float]:
    source_arr = np.array(source_image)
    template_arr = np.array(template_image)
    source_height, source_width = source_arr.shape
    template_height, template_width = template_arr.shape

    # 结果矩阵，用于存储匹配得分
    result = np.zeros((source_height - template_height + 1, source_width - template_width + 1))

    # 遍历源图像所有可能的位置
    for y in range(result.shape[0]):
        for x in range(result.shape[1]):
            # 提取当前区域
            region = source_arr[y:y + template_height, x:x + template_width]
            # 计算匹配得分（这里使用均方误差）
            error = np.sum((region - template_arr) ** 2)
            result[y, x] = error

    # 找到最小误差的位置
    min_val = np.min(result)
    min_loc = np.unravel_index(np.argmin(result), result.shape)
    
    #min_loc为坐标, min_val是匹配分数
    return min_loc, min_val


async def gradient_magnitude_and_direction(image):
    # 计算图像的梯度幅度和方向
    # Sobel 算子
    sobel_x = np.array([[1, 0, -1],
                         [2, 0, -2],
                         [1, 0, -1]])

    sobel_y = np.array([[1, 2, 1],
                         [0, 0, 0],
                         [-1, -2, -1]])
    
    pixels = np.array(image)
    gradient_magnitude = np.zeros_like(pixels, dtype=float)
    gradient_direction = np.zeros_like(pixels, dtype=float)

    for y in range(1, pixels.shape[0] - 1):
        for x in range(1, pixels.shape[1] - 1):
            gx = np.sum(sobel_x * pixels[y-1:y+2, x-1:x+2])
            gy = np.sum(sobel_y * pixels[y-1:y+2, x-1:x+2])
            gradient_magnitude[y, x] = np.sqrt(gx**2 + gy**2)
            gradient_direction[y, x] = np.arctan2(gy, gx) * (180 / np.pi) % 180

    return gradient_magnitude, gradient_direction

async def non_maximum_suppression(magnitude, direction):
    # 非极大值抑制
    suppressed = np.zeros_like(magnitude)

    for y in range(1, magnitude.shape[0]-1):
        for x in range(1, magnitude.shape[1]-1):
            angle = direction[y, x]
            
            # 确定相邻像素
            if (angle < 22.5 or angle >= 157.5):  # 0度
                neighbors = [magnitude[y, x-1], magnitude[y, x+1]]
            elif (22.5 <= angle < 67.5):  # 45度
                neighbors = [magnitude[y-1, x+1], magnitude[y+1, x-1]]
            elif (67.5 <= angle < 112.5):  # 90度
                neighbors = [magnitude[y-1, x], magnitude[y+1, x]]
            else:  # 135度
                neighbors = [magnitude[y-1, x-1], magnitude[y+1, x+1]]

            if magnitude[y, x] >= max(neighbors):
                suppressed[y, x] = magnitude[y, x]

    return suppressed

async def double_threshold(image, low, high):
    # 双阈值处理
    strong = 255
    weak = 75
    result = np.zeros_like(image)

    strong_i, strong_j = np.where(image >= high)
    weak_i, weak_j = np.where((image <= high) & (image >= low))
    
    result[strong_i, strong_j] = strong
    result[weak_i, weak_j] = weak
    
    return result

async def hysteresis_edges(image):
    # 滞后阈值处理
    strong_i, strong_j = np.where(image == 255)
    
    for i, j in zip(strong_i, strong_j):
        for y in range(i-1, i+2):
            for x in range(j-1, j+2):
                if 0 <= y < image.shape[0] and 0 <= x < image.shape[1]:
                    if image[y, x] == 75:
                        image[y, x] = 255
                        
    return image

async def canny_edge_detection(image: ImageFile):
    # 完整的 Canny 边缘检测流程
    # 传入一个经过二值处理的图像
    gradient_magnitude, gradient_direction = await gradient_magnitude_and_direction(np.array(image))
    
    nms_image = await non_maximum_suppression(gradient_magnitude, gradient_direction)
    
    thresholded_image = await double_threshold(nms_image, low=50, high=150)
    
    final_edges = await hysteresis_edges(thresholded_image)
    return Image.fromarray(final_edges.astype(np.uint8))

# 保留的cv2库识别代码
# async def cv2_process(path_bg, path_bk)
#     #背景处理
#     bg_img = cv2.imread("./bg.jpg")
#     #灰度处理
#     bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
#     #噪点处理
#     bg_deno = cv2.fastNlMeansDenoising(bg_gray, None, 10, 7, 21)
#     #Otsu’s二值化
#     ret2,bg_th = cv2.threshold(bg_deno,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
#     #边沿检测
#     bg_canny = cv2.Canny(bg_th, threshold1=500, threshold2=900, apertureSize=3)

#     #滑块处理
#     block_img = cv2.imread("./block.png")
#     block_gray = cv2.cvtColor(block_img, cv2.COLOR_BGR2GRAY)
#     #反色
#     block_opsite = cv2.bitwise_not(block_gray)
#     #简单二值化
#     ret, bthimg = cv2.threshold(block_opsite, 240, 255, cv2.THRESH_BINARY_INV)
#     block_canny = cv2.Canny(bthimg, threshold1=500, threshold2=900, apertureSize=3)
    
#     result = cv2.matchTemplate(bg_canny, block_canny, cv2.TM_CCOEFF_NORMED)

#     # 获取匹配结果的位置
#     min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
#     top_left2 = max_loc
#     bottom_right2 = (top_left2[0] + block_img.shape[1], top_left2[1] + block_img.shape[0])

#     # 在输入图像上绘制矩形标记
#     cv2.imwrite('./bg.jpg', cv2.rectangle(bg_img, top_left2, bottom_right2, (0, 0, 255), 2))

#     return max_loc