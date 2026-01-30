from fastapi import APIRouter, UploadFile, File, Form, Depends
import os
import tempfile
import zipfile
import shutil
import time

from gpustack.config import get_global_config
from gpustack.api.auth import get_current_user

router = APIRouter()


@router.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    type: str = Form(...),
    current_user=Depends(get_current_user),
):
    """
    上传文件压缩包并解压到指定目录

    Args:
        file: 上传的文件压缩包
        type: 文件类型，可选值为"dataset"或"model"
        current_user: 当前登录用户

    Returns:
        解压后的文件路径
    """
    # 验证文件类型
    if type not in ["dataset", "model"]:
        return {"error": "Invalid type. Must be 'dataset' or 'model'"}

    # 获取配置的存储目录
    config = get_global_config()
    storage_dir = config.storage_dir

    # 创建临时目录用于解压
    with tempfile.TemporaryDirectory() as temp_dir:
        # 保存上传的文件
        file_path = os.path.join(temp_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 检查文件是否为zip格式
        if not zipfile.is_zipfile(file_path):
            return {"error": "File must be a zip archive"}

        # 解压文件
        extract_dir = os.path.join(temp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        # 获取解压后的顶部文件夹
        top_level_items = os.listdir(extract_dir)
        if not top_level_items:
            return {"error": "Zip file is empty"}

        top_level_dir = os.path.join(extract_dir, top_level_items[0])
        if not os.path.isdir(top_level_dir):
            return {"error": "Zip file must contain a top-level directory"}

        # 构建目标目录路径，添加时间戳防止重复
        timestamp = int(time.time())
        dir_name = os.path.basename(top_level_dir)
        timestamped_dir_name = f"{timestamp}_{dir_name}"
        target_dir = os.path.join(storage_dir, type, timestamped_dir_name)

        # 如果目标目录已存在，先删除
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)

        # 移动解压后的目录到目标位置
        shutil.move(top_level_dir, target_dir)

        return {"path": target_dir}
