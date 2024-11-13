""" 
2024/11/13 by Kama with Claude.AI
主題:提供照片整理的小工具
功能:可找完全相同（md5）的 或 設定相似度來移動高相似的照片  
"""
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading
from queue import Queue
import os
import shutil
from typing import List, Set, Dict, Tuple
from datetime import datetime
import hashlib
from PIL import Image
import numpy as np
import imagehash
from dataclasses import dataclass
from collections import defaultdict
import logging

@dataclass
class PhotoInfo:
    """存儲照片資訊的數據類"""
    path: Path
    hash_value: str
    image_hash: str = None
    shoot_date: datetime = None
    modify_date: datetime = None

class PhotoDuplicateHandler:
    def __init__(self, source_dirs: List[str], similarity_threshold: float = 0.95, exact_match_only: bool = False):
        """
        初始化照片重複處理器
        
        Args:
            source_dirs: 要掃描的來源目錄列表
            similarity_threshold: 相似度閾值，預設為0.95（95%）
            exact_match_only: 是否僅檢查完全相同的檔案
        """
        self.source_dirs = [Path(d) for d in source_dirs]
        self.similarity_threshold = similarity_threshold
        self.exact_match_only = exact_match_only
        self.setup_logging()
        
    def setup_logging(self):
        """設定日誌記錄"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(message)s',
            handlers=[
                logging.FileHandler('photo_duplicate_handler.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    
    def calculate_file_hash(self, filepath: Path) -> str:
        """計算檔案的 MD5 雜湊值"""
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def get_image_shoot_date(self, image_path: Path) -> datetime:
        """
        獲取照片的拍攝日期
        
        Args:
            image_path: 照片檔案路徑
            
        Returns:
            拍攝日期，如果無法獲取則返回None
        """
        try:
            with Image.open(image_path) as img:
                exif = img._getexif()
                if exif:
                    # 嘗試獲取不同的EXIF日期標籤
                    date_taken = None
                    for tag_id in (36867, 36868, 306):  # DateTimeOriginal, DateTimeDigitized, DateTime
                        if tag_id in exif:
                            try:
                                date_str = exif[tag_id]
                                date_taken = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
                                break
                            except (ValueError, TypeError):
                                continue
                    return date_taken
        except Exception as e:
            logging.warning(f"無法讀取照片 {image_path} 的EXIF資訊: {str(e)}")
        return None
    
    def get_file_modified_date(self, file_path: Path) -> datetime:
        """獲取檔案的修改日期"""
        return datetime.fromtimestamp(os.path.getmtime(file_path))
    
    def calculate_image_hash(self, filepath: Path) -> str:
        """計算圖片的感知雜湊值"""
        try:
            with Image.open(filepath) as img:
                if img.mode != 'L':
                    img = img.convert('L')
                hash_value = str(imagehash.average_hash(img))
                return hash_value
        except Exception as e:
            logging.warning(f"無法計算圖片雜湊值 {filepath}: {str(e)}")
            return None

    def calculate_similarity(self, hash1: str, hash2: str) -> float:
        """計算兩個感知雜湊值的相似度"""
        if not hash1 or not hash2:
            return 0.0
        
        bin1 = bin(int(hash1, 16))[2:].zfill(64)
        bin2 = bin(int(hash2, 16))[2:].zfill(64)
        
        hamming_distance = sum(b1 != b2 for b1, b2 in zip(bin1, bin2))
        
        similarity = 1 - (hamming_distance / 64.0)
        return similarity
    
    def get_photo_files(self) -> Dict[str, List[PhotoInfo]]:
        """掃描所有目錄並建立照片資訊對照表"""
        photo_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp'}
        hash_map: Dict[str, List[PhotoInfo]] = defaultdict(list)
        
        total_files = sum(1 for d in self.source_dirs for _ in d.rglob("*"))
        processed_files = 0
        
        for source_dir in self.source_dirs:
            for file_path in source_dir.rglob("*"):
                processed_files += 1
                if processed_files % 100 == 0:
                    print(f"處理進度: {processed_files}/{total_files} 檔案")
                    
                if file_path.suffix.lower() in photo_extensions:
                    try:
                        file_hash = self.calculate_file_hash(file_path)
                        image_hash = self.calculate_image_hash(file_path)
                        shoot_date = self.get_image_shoot_date(file_path)
                        modify_date = self.get_file_modified_date(file_path)
                        
                        photo_info = PhotoInfo(
                            path=file_path,
                            hash_value=file_hash,
                            image_hash=image_hash,
                            shoot_date=shoot_date,
                            modify_date=modify_date
                        )
                        hash_map[file_hash].append(photo_info)
                    except Exception as e:
                        logging.error(f"處理檔案時發生錯誤 {file_path}: {str(e)}")
        
        return hash_map

    def sort_photos_by_date_and_name(self, photos: List[PhotoInfo]) -> List[PhotoInfo]:
        """根據建立日期和檔名長度排序照片
        
        排序規則：
        1. 建立日期較早的排在前面
        2. 建立日期相同時，檔名較短的排在前面
        
        Args:
            photos: 要排序的照片列表
            
        Returns:
            排序後的照片列表，保留的照片（日期最早或檔名最短）會排在第一個
        """
        def get_compare_key(photo: PhotoInfo) -> tuple:
            create_date = photo.shoot_date or photo.modify_date or datetime.max
            filename_length = len(photo.path.stem)  # 只計算不含副檔名的檔名長度
            return (create_date, filename_length)
        
        return sorted(photos, key=get_compare_key)

    def find_similar_images(self, photos: List[PhotoInfo]) -> List[List[PhotoInfo]]:
        """找出相似的圖片群組，排除完全相同的檔案"""
        similar_groups = []
        processed = set()
        
        # 先將相同MD5的照片分組，並記錄它們的路徑
        md5_groups = defaultdict(list)
        exact_match_paths = set()
        for photo in photos:
            md5_groups[photo.hash_value].append(photo)
            if len(md5_groups[photo.hash_value]) > 1:
                for p in md5_groups[photo.hash_value]:
                    exact_match_paths.add(p.path)
        
        # 只處理不在完全相同組中的照片
        unique_photos = [p for p in photos if p.path not in exact_match_paths]
        
        # 對剩餘的照片進行相似度比對
        for i, photo1 in enumerate(unique_photos):
            if photo1.path in processed:
                continue
                
            current_group = [photo1]
            processed.add(photo1.path)
            
            for photo2 in unique_photos[i+1:]:
                if photo2.path not in processed:
                    similarity = self.calculate_similarity(photo1.image_hash, photo2.image_hash)
                    if similarity >= self.similarity_threshold:
                        current_group.append(photo2)
                        processed.add(photo2.path)
            
            if len(current_group) > 1:
                similar_groups.append(current_group)
                
        return similar_groups

    def handle_duplicates(self) -> Set[Path]:
        """處理重複的照片檔案"""
        hash_map = self.get_photo_files()
        processed_dirs: Set[Path] = set()
        
        if self.exact_match_only:
            # 只處理完全相同的檔案
            for file_hash, photo_infos in hash_map.items():
                if len(photo_infos) > 1:
                    self._process_duplicate_group(photo_infos, "完全相同", processed_dirs)
        else:
            # 只處理相似檔案，收集所有照片進行相似度比對
            all_photos = []
            for photo_infos in hash_map.values():
                all_photos.extend(photo_infos)
            
            # 尋找相似的檔案
            similar_groups = self.find_similar_images(all_photos)
            for group in similar_groups:
                self._process_duplicate_group(group, "相似", processed_dirs)
        
        return processed_dirs

    def _process_duplicate_group(self, photo_infos: List[PhotoInfo], duplicate_type: str, processed_dirs: Set[Path]):
        """處理一組重複或相似的照片，根據日期和檔名決定要保留的版本"""
        sorted_photos = self.sort_photos_by_date_and_name(photo_infos)
        keep_photo = sorted_photos[0]
        
        # 決定日期類型（建立或修改）
        date_type = "拍攝" if keep_photo.shoot_date else "修改"
        keep_date = keep_photo.shoot_date or keep_photo.modify_date
        
        # 如果是完全相同的檔案，記錄保留檔案的原因
        if duplicate_type == "完全相同":
            for i, photo in enumerate(sorted_photos[1:], 1):
                photo_date = photo.shoot_date or photo.modify_date
                if photo_date == keep_date:
                    keep_reason = f"檔名較短({len(keep_photo.path.stem)}字元 < {len(photo.path.stem)}字元)"
                else:
                    keep_reason = f"{date_type}日期較早({keep_date:%Y-%m-%d_%H-%M-%S})"
        
        for idx, photo_info in enumerate(sorted_photos[1:], 1):
            duplicate_dir = photo_info.path.parent / f"{photo_info.path.parent.name}重複"
            duplicate_dir.mkdir(exist_ok=True)
            
            # 使用原始檔名
            new_name = photo_info.path.name
            new_path = duplicate_dir / new_name
            
            try:
                # 如果目標路徑已存在，則在檔名後加上編號
                if new_path.exists():
                    counter = 1
                    while new_path.exists():
                        stem = photo_info.path.stem
                        suffix = photo_info.path.suffix
                        new_name = f"{stem}({counter}){suffix}"
                        new_path = duplicate_dir / new_name
                        counter += 1

                shutil.move(str(photo_info.path), str(new_path))
                
                # 記錄完整的處理資訊到日誌
                photo_date = photo_info.shoot_date or photo_info.modify_date
                if duplicate_type == "完全相同":
                    if photo_date == keep_date:
                        move_reason = f"檔名較長({len(photo_info.path.stem)}字元)"
                    else:
                        move_reason = f"{date_type}日期較晚({photo_date:%Y-%m-%d_%H-%M-%S})"
                    
                    logging.info(
                        f"{duplicate_type}檔案已處理: {photo_info.path} -> {new_path}\n"
                        f"原因: {move_reason}\n"
                        f"保留的檔案: {keep_photo.path}"
                    )
                else:
                    logging.info(
                        f"{duplicate_type}檔案已處理: {photo_info.path} -> {new_path}\n"
                        f"相似度超過閾值，保留較早的檔案: {keep_photo.path}\n"
                        f"移動檔案的{date_type}日期: {photo_date:%Y-%m-%d_%H-%M-%S}"
                    )
                    
            except Exception as e:
                logging.error(f"移動檔案時發生錯誤: {str(e)}")
            
            processed_dirs.add(duplicate_dir)

class DuplicatePhotoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("重複照片處理工具")
        
        # 設定視窗大小和位置
        window_width = 600
        window_height = 500
        
        # 取得螢幕尺寸
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        
        # 計算視窗置中的位置
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        # 設定視窗大小和位置
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # 設定視窗樣式
        self.style = ttk.Style()
        self.style.configure('TButton', padding=3)  # 減少按鈕內邊距
        self.style.configure('TLabel', padding=2)   # 減少標籤內邊距
        
        self.setup_ui()
        self.source_dirs = []
        self.processing = False
        self.message_queue = Queue()
        
    def setup_ui(self):
        """設置使用者介面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="5")  # 減少主框架內邊距
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 目錄選擇區域
        dir_frame = ttk.LabelFrame(main_frame, text="選擇掃描目錄", padding="3")  # 減少框架內邊距
        dir_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        
        self.dir_listbox = tk.Listbox(dir_frame, height=4)  # 減少列表高度
        self.dir_listbox.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E))
        
        ttk.Button(dir_frame, text="新增目錄", command=self.add_directory).grid(row=1, column=0, padx=3, pady=2)
        ttk.Button(dir_frame, text="移除選擇的目錄", command=self.remove_directory).grid(row=1, column=1, padx=3, pady=2)
        
        # 相似度設定
        sim_frame = ttk.LabelFrame(main_frame, text="相似度設定", padding="3")
        sim_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        
        # 新增完全相同勾選框
        self.exact_match_var = tk.BooleanVar(value=False)
        self.exact_match_check = ttk.Checkbutton(
            sim_frame, 
            text="僅尋找完全相同的照片",
            variable=self.exact_match_var,
            command=self.toggle_similarity_entry
        )
        self.exact_match_check.grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=3, pady=2)
        
        ttk.Label(sim_frame, text="相似度閾值 (%)：").grid(row=1, column=0)
        self.similarity_var = tk.StringVar(value="95")
        self.similarity_entry = ttk.Entry(sim_frame, textvariable=self.similarity_var, width=8)  # 減少輸入框寬度
        self.similarity_entry.grid(row=1, column=1, padx=3)
        
        # 進度顯示
        progress_frame = ttk.LabelFrame(main_frame, text="處理進度", padding="3")
        progress_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        
        self.progress_var = tk.StringVar(value="準備就緒")
        ttk.Label(progress_frame, textvariable=self.progress_var).grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='indeterminate')
        self.progress_bar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=2)
        
        # 日誌顯示
        log_frame = ttk.LabelFrame(main_frame, text="處理日誌", padding="3")
        log_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=2)
        
        self.log_text = tk.Text(log_frame, height=8, wrap=tk.WORD)  # 減少文字區域高度
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.log_text['yscrollcommand'] = scrollbar.set
        
        # 控制按鈕
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=5)
        
        self.start_button = ttk.Button(button_frame, text="開始處理", command=self.start_processing)
        self.start_button.grid(row=0, column=0, padx=3)
        
        ttk.Button(button_frame, text="退出", command=self.root.quit).grid(row=0, column=1, padx=3)
        
        # 配置grid權重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
    def add_directory(self):
        """新增目錄到清單"""
        directory = filedialog.askdirectory()
        if directory:
            self.source_dirs.append(directory)
            self.dir_listbox.insert(tk.END, directory)
            self.log_message(f"新增目錄: {directory}")
    
    def remove_directory(self):
        """從清單中移除選擇的目錄"""
        selection = self.dir_listbox.curselection()
        if selection:
            index = selection[0]
            directory = self.dir_listbox.get(index)
            self.dir_listbox.delete(index)
            self.source_dirs.remove(directory)
            self.log_message(f"移除目錄: {directory}")
    
    def log_message(self, message: str):
        """新增訊息到日誌視窗"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
    
    def toggle_similarity_entry(self):
        """切換相似度輸入欄位的啟用狀態"""
        if self.exact_match_var.get():
            self.similarity_entry.state(['disabled'])
        else:
            self.similarity_entry.state(['!disabled'])
    
    def update_progress(self):
        """更新進度顯示"""
        if self.processing:
            try:
                while not self.message_queue.empty():
                    message = self.message_queue.get_nowait()
                    self.progress_var.set(message)
                    self.log_message(message)
            except:
                pass
            self.root.after(100, self.update_progress)
    
    def start_processing(self):
        """開始處理重複照片"""
        if not self.source_dirs:
            messagebox.showerror("錯誤", "請先選擇至少一個掃描目錄！")
            return
        
        try:
            similarity = float(self.similarity_var.get())
            if not 0 <= similarity <= 99:  # 修改最大值為99
                raise ValueError()
        except ValueError:
            messagebox.showerror("錯誤", "請輸入有效的相似度數值（0-99）！")  # 修改錯誤訊息
            return
        
        if not self.processing:
            self.processing = True
            self.start_button.state(['disabled'])
            self.progress_bar.start(10)
            self.progress_var.set("正在處理中...")
            
            # 在新執行緒中執行處理
            thread = threading.Thread(target=self.process_duplicates, args=(similarity/100,))
            thread.daemon = True
            thread.start()
            
            # 開始更新進度
            self.update_progress()
    
    def process_duplicates(self, similarity_threshold: float):
        """在新執行緒中處理重複照片"""
        try:
            handler = PhotoDuplicateHandler(
                self.source_dirs, 
                similarity_threshold,
                exact_match_only=self.exact_match_var.get()
            )
            processed_dirs = handler.handle_duplicates()
            
            # 處理完成後在主執行緒中更新UI
            self.root.after(0, self.processing_completed, processed_dirs)
        except Exception as e:
            self.root.after(0, self.processing_error, str(e))
    
    def processing_completed(self, processed_dirs: Set[Path]):
        """處理完成後的回調"""
        self.processing = False
        self.progress_bar.stop()
        self.start_button.state(['!disabled'])
        self.progress_var.set("處理完成！")
        
        # 顯示結果
        result_message = "處理完成！\n\n重複檔案已移至以下目錄：\n"
        for dir_path in processed_dirs:
            result_message += f"- {dir_path}\n"
        
        messagebox.showinfo("完成", result_message)
        self.log_message("處理完成")
    
    def processing_error(self, error_message: str):
        """處理錯誤的回調"""
        self.processing = False
        self.progress_bar.stop()
        self.start_button.state(['!disabled'])
        self.progress_var.set("處理失敗")
        
        messagebox.showerror("錯誤", f"處理過程中發生錯誤：\n{error_message}")
        self.log_message(f"錯誤：{error_message}")

def main():
    """主程式入口"""
    root = tk.Tk()
    app = DuplicatePhotoApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
