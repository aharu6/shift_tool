import os
import tkinter
from tkinter import filedialog

def main():
    iDir = os.path.abspath(os.path.dirname(__file__))
    selected_dir = filedialog.askdirectory(
        message = "12ヶ月分のシフトが入ったフォルダを選択してください",
        initialdir = iDir,
    )
    print(f"選択されたディレクトリ: {selected_dir}")
    
if __name__ == "__main__":
    main()
