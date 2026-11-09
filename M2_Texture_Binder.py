#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Textures[0] 开始，按 TXT 顺序绑定或替换 HARDCODED (0) 贴图路径。"""

import os
import struct
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


TEXTURE_TYPES = {
    0: "HARDCODED (0)",
    1: "SKIN (1)",
    2: "OBJECT_SKIN (2)",
    3: "WEAPON_BLADE (3)",
    4: "WEAPON_HANDLE (4)",
    5: "ENVIRONMENT (5)",
    6: "HAIR (6)",
    7: "FACIAL_HAIR (7)",
    8: "SKIN_EXTRA (8)",
    9: "UI_SKIN (9)",
    10: "TAUREN_MANE (10)",
    11: "MONSTER_SKIN_1 (11)",
    12: "MONSTER_SKIN_2 (12)",
    13: "MONSTER_SKIN_3 (13)",
    14: "ITEM_ICON (14)",
}


class M2Error(Exception):
    pass


def texture_type_name(value):
    return TEXTURE_TYPES.get(value, "其他类型 (%d)" % value)


def read_m2(path):
    data = Path(path).read_bytes()
    if len(data) < 0x58:
        raise M2Error("文件过小，不是有效的 M2 模型。")

    magic = data[:4]
    if magic == b"MD20":
        base = 0
        kind = "MD20"
    elif magic == b"MD21":
        base = 8
        kind = "MD21"
        md21_size = struct.unpack_from("<I", data, 4)[0]
        if 8 + md21_size > len(data):
            raise M2Error("MD21 数据块超出文件末尾，文件可能已损坏。")
    else:
        raise M2Error("不是受支持的 M2 文件：文件头必须是 MD20 或 MD21。")

    if base + 0x58 > len(data):
        raise M2Error("M2 文件头不完整。")
    version = struct.unpack_from("<I", data, base + 4)[0]
    if magic == b"MD20" and version != 264:
        raise M2Error("MD20 仅支持 v264，当前文件版本为 %d。" % version)

    count, textures_offset = struct.unpack_from("<II", data, base + 0x50)
    if count > 4096:
        raise M2Error("Textures 数量异常：%d。" % count)
    table_start = base + textures_offset
    table_end = table_start + count * 16
    if table_start < base or table_end > len(data):
        raise M2Error("Textures 表超出文件末尾，无法安全修改。")

    records = []
    for index in range(count):
        position = table_start + index * 16
        texture_type, flags, name_length, name_offset = struct.unpack_from("<IIII", data, position)
        old_path = ""
        if texture_type == 0 and name_length and name_offset:
            start = base + name_offset
            end = start + name_length
            if start < base or end > len(data):
                raise M2Error("Textures[%d] 的贴图路径超出文件末尾。" % index)
            old_path = data[start:end].split(b"\x00", 1)[0].decode("utf-8", "replace")
        records.append({
            "index": index,
            "position": position,
            "type": texture_type,
            "flags": flags,
            "path": old_path,
        })

    return {
        "data": data,
        "base": base,
        "kind": kind,
        "version": version,
        "records": records,
    }


def read_texture_paths(path):
    raw = Path(path).read_bytes()
    text = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise M2Error("无法识别 TXT 编码，请使用 UTF-8 或 ANSI 保存。")

    # 保留空行：TXT 第 N 行永远对应 Textures[N-1]，不能向前递补。
    paths = [line.strip() for line in text.splitlines()]
    if not paths or not any(paths):
        raise M2Error("TXT 中没有可绑定或替换的贴图路径。")
    if any("\x00" in value for value in paths):
        raise M2Error("贴图路径中不能包含 NUL 字符。")
    return paths


def prepare_binding(m2_path, txt_path):
    info = read_m2(m2_path)
    paths = read_texture_paths(txt_path)
    records = info["records"]
    if len(paths) > len(records):
        raise M2Error(
            "TXT 有 %d 行，但模型只有 %d 个 Textures 槽位；请减少 TXT 行数。"
            % (len(paths), len(records))
        )

    bindings = {}
    for index, texture_path in enumerate(paths):
        if not texture_path or records[index]["type"] != 0:
            continue
        bindings[index] = texture_path
    if not bindings:
        raise M2Error("没有可执行的绑定或替换：路径可能为空，或对应槽位均为非 0 类型。")
    return info, paths, bindings


def make_report(info, paths, bindings):
    records = info["records"]
    hardcoded_count = sum(record["type"] == 0 for record in records)
    bind_count = sum(not records[index]["path"] for index in bindings)
    replace_count = len(bindings) - bind_count
    lines = [
        "模型格式：%s，版本：%d" % (info["kind"], info["version"]),
        "Textures：%d 个；HARDCODED：%d 个；非 0 类型：%d 个"
        % (len(records), hardcoded_count, len(records) - hardcoded_count),
        "TXT 行号与槽位号一一对应：第 N 行 → Textures[N-1]",
        "本次绑定空槽位：%d 个；替换已有路径：%d 个" % (bind_count, replace_count),
        "",
    ]
    for record in records:
        index = record["index"]
        supplied = paths[index] if index < len(paths) else None
        if record["type"] != 0:
            message = "Textures[%d]  跳过：%s" % (index, texture_type_name(record["type"]))
            if supplied:
                message += "；TXT 第 %d 行同步跳过" % (index + 1)
            lines.append(message)
        elif index in bindings:
            if record["path"]:
                lines.append("Textures[%d]  替换：%s" % (index, record["path"]))
            else:
                lines.append("Textures[%d]  绑定空槽位：（原路径为空）" % index)
            lines.append("             → %s（TXT 第 %d 行）" % (bindings[index], index + 1))
        elif supplied == "":
            lines.append("Textures[%d]  TXT 第 %d 行为空，保留原路径：%s"
                         % (index, index + 1, record["path"] or "（空）"))
        else:
            lines.append("Textures[%d]  未提供对应 TXT 行，保留原路径：%s"
                         % (index, record["path"] or "（空）"))
    return "\n".join(lines)


def prepare_name_change(m2_path, old_name, new_name):
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not old_name:
        raise M2Error("请输入要查找的旧名称。")
    if old_name == new_name:
        raise M2Error("旧名称和新名称相同，无需转换。")

    info = read_m2(m2_path)
    changes = {}
    for record in info["records"]:
        if record["type"] == 0 and old_name in record["path"]:
            changed = record["path"].replace(old_name, new_name)
            if changed != record["path"]:
                changes[record["index"]] = changed
    if not changes:
        raise M2Error("HARDCODED 路径中没有找到：%s" % old_name)
    return info, changes


def make_name_report(info, old_name, new_name, changes):
    lines = [
        "名称转换：%s → %s" % (old_name, new_name),
        "仅处理 HARDCODED (0)，共修改 %d 个槽位；非 0 类型保持不变。" % len(changes),
        "",
    ]
    for record in info["records"]:
        index = record["index"]
        if index in changes:
            lines.append("Textures[%d]  %s" % (index, record["path"]))
            lines.append("             → %s" % changes[index])
    return "\n".join(lines)


def write_bound_m2(m2_path, output_path, info, bindings):
    source = os.path.normcase(os.path.abspath(str(m2_path)))
    output = os.path.normcase(os.path.abspath(str(output_path)))
    if source == output:
        raise M2Error("为保护原模型，输出文件不能与输入 M2 相同。")

    modified = bytearray(info["data"])
    base = info["base"]
    for record in info["records"]:
        index = record["index"]
        if index not in bindings:
            continue
        encoded = bindings[index].encode("utf-8") + b"\x00"
        absolute_offset = len(modified)
        modified.extend(encoded)
        relative_offset = absolute_offset - base
        if relative_offset > 0xFFFFFFFF:
            raise M2Error("输出文件过大，贴图路径偏移超出 32 位范围。")
        struct.pack_into("<II", modified, record["position"] + 8, len(encoded), relative_offset)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        temporary.write_bytes(modified)
        os.replace(str(temporary), str(output_path))
    finally:
        if temporary.exists():
            temporary.unlink()
    return len(modified)


class BinderGUI:
    def __init__(self, root):
        self.root = root
        self.m2_var = tk.StringVar()
        self.txt_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.old_name_var = tk.StringVar()
        self.new_name_var = tk.StringVar()
        self.last_output = None

        root.title("M2 贴图绑定／替换与名称转换工具")
        root.geometry("960x840")
        root.minsize(860, 700)

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        hint = (
            "TXT 第 N 行严格对应 Textures[N-1]。仅处理 HARDCODED (0)：空路径绑定、已有路径替换；"
            "非 0 槽位及其对应 TXT 行一起跳过，空行用于保留对应槽位。"
        )
        ttk.Label(outer, text=hint, wraplength=900, foreground="#444").grid(
            row=0, column=0, sticky="w", pady=(0, 10))

        files = ttk.LabelFrame(outer, text="文件选择", padding=10)
        files.grid(row=1, column=0, sticky="ew")
        files.columnconfigure(1, weight=1)
        self.add_path_row(files, 0, "输入 M2：", self.m2_var, self.pick_m2)
        self.add_path_row(files, 1, "贴图路径 TXT：", self.txt_var, self.pick_txt)
        self.add_path_row(files, 2, "输出 M2：", self.output_var, self.pick_output)

        names = ttk.LabelFrame(outer, text="名称批量转换（仅 HARDCODED 路径）", padding=10)
        names.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        names.columnconfigure(1, weight=1)
        names.columnconfigure(3, weight=1)
        ttk.Label(names, text="旧名称：").grid(row=0, column=0, sticky="w")
        ttk.Entry(names, textvariable=self.old_name_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(names, text="新名称：").grid(row=0, column=2, sticky="w")
        ttk.Entry(names, textvariable=self.new_name_var).grid(row=0, column=3, sticky="ew", padx=8)
        ttk.Button(names, text="预览名称转换", command=self.preview_names).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(names, text="转换并保存", command=self.convert_names).grid(
            row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        ttk.Label(names, text="替换路径中的所有匹配文字，区分大小写。", foreground="#666").grid(
            row=1, column=2, columnspan=2, sticky="w", padx=8, pady=(8, 0))

        actions = ttk.LabelFrame(outer, text="TXT 绑定／替换", padding=8)
        actions.grid(row=3, column=0, sticky="ew", pady=10)
        ttk.Button(actions, text="预览 TXT 对应关系", command=self.preview).pack(side="left")
        ttk.Button(actions, text="按 TXT 绑定／替换并保存", command=self.bind).pack(side="left", padx=8)
        self.open_button = ttk.Button(actions, text="打开输出目录", command=self.open_folder,
                                      state="disabled")
        self.open_button.pack(side="left")

        log_box = ttk.LabelFrame(outer, text="预览与日志", padding=6)
        log_box.grid(row=4, column=0, sticky="nsew")
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log = tk.Text(log_box, wrap="none", font=("Microsoft YaHei UI", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(log_box, orient="horizontal", command=self.log.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.log.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.set_log("TXT 行号必须与 Textures 槽位号一一对应。\n\n"
                     "例如 Textures[2] 为非 0 类型：\n"
                     "第 3 行会被跳过，Textures[3] 使用第 4 行。\n\n"
                     "名称转换示例：\n旧名称：winterbroom\n新名称：winterbroom23")

    def add_path_row(self, parent, row, label, variable, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(parent, text="浏览…", command=command).grid(row=row, column=2, pady=4)

    def pick_m2(self):
        path = filedialog.askopenfilename(
            title="选择 M2 模型", filetypes=[("M2 模型", "*.m2"), ("所有文件", "*.*")])
        if path:
            self.m2_var.set(path)
            source = Path(path)
            self.output_var.set(str(source.with_name(source.stem + "_贴图已更新.m2")))
            self.last_output = None
            self.open_button.configure(state="disabled")

    def pick_txt(self):
        path = filedialog.askopenfilename(
            title="选择贴图路径 TXT", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            self.txt_var.set(path)

    def pick_output(self):
        path = filedialog.asksaveasfilename(
            title="保存修改后的 M2", defaultextension=".m2",
            filetypes=[("M2 模型", "*.m2"), ("所有文件", "*.*")])
        if path:
            self.output_var.set(path)

    def set_log(self, text):
        self.log.delete("1.0", "end")
        self.log.insert("1.0", text)

    def validate_paths(self, need_output=False, require_txt=True):
        m2 = self.m2_var.get().strip()
        txt = self.txt_var.get().strip()
        if not m2 or not Path(m2).is_file():
            raise M2Error("请选择有效的输入 M2 文件。")
        if require_txt and (not txt or not Path(txt).is_file()):
            raise M2Error("请选择有效的贴图路径 TXT 文件。")
        output = self.output_var.get().strip()
        if need_output and not output:
            raise M2Error("请选择输出 M2 的保存位置。")
        return m2, txt, output

    def save_changes(self, m2, output, info, changes):
        if Path(output).suffix.lower() != ".m2":
            output = str(Path(output).with_suffix(".m2"))
            self.output_var.set(output)
        source = os.path.normcase(os.path.abspath(m2))
        target = os.path.normcase(os.path.abspath(output))
        if source == target:
            raise M2Error("为保护原模型，输出文件不能与输入 M2 相同。")
        if Path(output).exists():
            overwrite = messagebox.askyesno(
                "输出文件已存在", "是否覆盖输出文件？\n输入的原 M2 不会被修改。", parent=self.root)
            if not overwrite:
                return None
        size = write_bound_m2(m2, output, info, changes)
        self.last_output = Path(output)
        self.open_button.configure(state="normal")
        return output, size

    def preview(self):
        try:
            m2, txt, _ = self.validate_paths()
            info, paths, bindings = prepare_binding(m2, txt)
            self.set_log(make_report(info, paths, bindings))
        except (M2Error, OSError, ValueError) as exc:
            messagebox.showerror("无法预览", str(exc), parent=self.root)

    def bind(self):
        try:
            m2, txt, output = self.validate_paths(need_output=True)
            info, paths, bindings = prepare_binding(m2, txt)
            saved = self.save_changes(m2, output, info, bindings)
            if not saved:
                return
            output, size = saved
            report = make_report(info, paths, bindings)
            report += "\n\n更新完成：%d 个槽位\n已保存：%s\n文件大小：%d 字节" % (
                len(bindings), output, size)
            self.set_log(report)
            messagebox.showinfo("更新完成", "已更新 %d 个贴图槽位（包括绑定和替换）。\n\n输出文件：\n%s" % (
                len(bindings), output), parent=self.root)
        except (M2Error, OSError, ValueError) as exc:
            messagebox.showerror("更新失败", str(exc), parent=self.root)

    def preview_names(self):
        try:
            m2, _, _ = self.validate_paths(require_txt=False)
            old_name = self.old_name_var.get()
            new_name = self.new_name_var.get()
            info, changes = prepare_name_change(m2, old_name, new_name)
            self.set_log(make_name_report(info, old_name.strip(), new_name.strip(), changes))
        except (M2Error, OSError, ValueError) as exc:
            messagebox.showerror("无法预览名称转换", str(exc), parent=self.root)

    def convert_names(self):
        try:
            m2, _, output = self.validate_paths(need_output=True, require_txt=False)
            old_name = self.old_name_var.get()
            new_name = self.new_name_var.get()
            info, changes = prepare_name_change(m2, old_name, new_name)
            saved = self.save_changes(m2, output, info, changes)
            if not saved:
                return
            output, size = saved
            report = make_name_report(info, old_name.strip(), new_name.strip(), changes)
            report += "\n\n名称转换完成：%d 个槽位\n已保存：%s\n文件大小：%d 字节" % (
                len(changes), output, size)
            self.set_log(report)
            messagebox.showinfo("转换完成", "已转换 %d 个贴图槽位。\n\n输出文件：\n%s" % (
                len(changes), output), parent=self.root)
        except (M2Error, OSError, ValueError) as exc:
            messagebox.showerror("名称转换失败", str(exc), parent=self.root)

    def open_folder(self):
        if not self.last_output:
            return
        folder = str(self.last_output.parent)
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError as exc:
            messagebox.showerror("无法打开目录", str(exc), parent=self.root)


def resource_path(filename):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)


def main():
    root = tk.Tk()
    try:
        root.iconbitmap(resource_path("app.ico"))
    except (OSError, tk.TclError):
        pass
    BinderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
