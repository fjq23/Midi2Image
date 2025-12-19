# 在 Windows 上运行
import mido
# ✅ 只选 rtmidi 后端
mido.set_backend('mido.backends.rtmidi')

from mido import Message, MidiFile, MidiTrack
import time
from datetime import datetime
import sys
import os
import time
from threading import Event, Thread

# MIDI 音符编号转音符名称
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def note_number_to_name(note_number):
    """将 MIDI 音符编号转换为音符名称（如 C4, A#5）"""
    octave = (note_number // 12) - 1
    note_name = NOTE_NAMES[note_number % 12]
    return f"{note_name}{octave}"


def parse_midi_file(filepath):
    """解析 MIDI 文件并显示详细信息"""
    if not os.path.exists(filepath):
        print(f"错误: 文件 '{filepath}' 不存在！")
        return

    mid = MidiFile(filepath)

    print(f"\n{'=' * 60}")
    print(f"MIDI 文件: {filepath}")
    print(f"{'=' * 60}")
    print(f"格式类型: Type {mid.type}")
    print(f"轨道数量: {len(mid.tracks)}")
    print(f"时间分辨率: {mid.ticks_per_beat} ticks/beat")
    print(f"总时长: {mid.length:.2f} 秒")

    # 遍历每个轨道
    for track_idx, track in enumerate(mid.tracks):
        print(f"\n{'-' * 60}")
        print(f"轨道 {track_idx}: {track.name if track.name else '(无名称)'}")
        print(f"消息数量: {len(track)}")
        print(f"{'-' * 60}")

        current_time = 0  # 累计时间（ticks）
        tempo = 500000    # 默认速度（微秒/拍，对应 120 BPM）
        note_count = 0

        for msg in track:
            current_time += msg.time
            time_seconds = mido.tick2second(current_time, mid.ticks_per_beat, tempo)

            if msg.type == 'set_tempo':
                tempo = msg.tempo
                bpm = mido.tempo2bpm(tempo)
                print(f"  [{time_seconds:8.3f}s] 速度变更: {bpm:.1f} BPM")

            elif msg.type == 'note_on' and msg.velocity > 0:
                note_name = note_number_to_name(msg.note)
                print(f"  [{time_seconds:8.3f}s] 音符按下: {note_name:4} "
                      f"(编号:{msg.note:3}, 力度:{msg.velocity:3}, 通道:{msg.channel})")
                note_count += 1

            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                note_name = note_number_to_name(msg.note)
                print(f"  [{time_seconds:8.3f}s] 音符释放: {note_name:4} "
                      f"(编号:{msg.note:3}, 通道:{msg.channel})")

            elif msg.type == 'control_change':
                # 常见控制器名称
                cc_names = {
                    1: '调制轮', 7: '音量', 10: '声相', 11: '表情',
                    64: '延音踏板', 65: '滑音踏板', 66: '持续踏板', 67: '柔音踏板'
                }
                cc_name = cc_names.get(msg.control, f'CC{msg.control}')
                print(f"  [{time_seconds:8.3f}s] 控制器: {cc_name} = {msg.value}")

            elif msg.type == 'program_change':
                print(f"  [{time_seconds:8.3f}s] 音色切换: Program {msg.program}")

            elif msg.type == 'pitchwheel':
                print(f"  [{time_seconds:8.3f}s] 弯音轮: {msg.pitch}")

            elif msg.is_meta:
                if msg.type == 'track_name':
                    print(f"  [{time_seconds:8.3f}s] 轨道名称: {msg.name}")
                elif msg.type == 'time_signature':
                    print(f"  [{time_seconds:8.3f}s] 拍号: {msg.numerator}/{msg.denominator}")
                elif msg.type == 'key_signature':
                    print(f"  [{time_seconds:8.3f}s] 调号: {msg.key}")
                elif msg.type == 'end_of_track':
                    print(f"  [{time_seconds:8.3f}s] 轨道结束")

        print(f"\n  轨道 {track_idx} 共有 {note_count} 个音符")

    print(f"\n{'=' * 60}")
    print("解析完成！")


def list_midi_input_ports():
    print("=== 可用 MIDI 输入端口 ===")
    # ✅ 这里加上 api='WINDOWS_MM'（rtmidi 的 API 名）
    ports = mido.get_input_names(api='WINDOWS_MM')
    if not ports:
        print("（当前没有检测到任何 MIDI 输入设备）")
    else:
        for i, p in enumerate(ports):
            print(f"[{i}] {p}")
    return ports


def list_midi_output_ports():
    print("=== 可用 MIDI 输出端口（用于监听回放） ===")
    ports = mido.get_output_names(api='WINDOWS_MM')
    if not ports:
        print("（当前没有检测到任何 MIDI 输出设备，无法直接回放）")
    else:
        for i, p in enumerate(ports):
            print(f"[{i}] {p}")
    return ports


def main():
    ports = list_midi_input_ports()
    if not ports:
        print("没有找到 MIDI 输入端口！")
        return

    # 选择端口并做基本校验
    while True:
        choice = input("选择要打开的端口编号: ").strip()
        if not choice.isdigit():
            print("请输入数字编号。")
            continue
        port_id = int(choice)
        if not (0 <= port_id < len(ports)):
            print("编号超出范围，请重新输入。")
            continue
        break

    port_name = ports[port_id]

    # 监听回放的输出端口（可选）
    out_ports = list_midi_output_ports()
    outport = None
    if out_ports:
        choice_out = input("选择监听输出端口编号（回车跳过）: ").strip()
        if choice_out:
            if not choice_out.isdigit():
                print("非数字编号，跳过监听回放。")
            else:
                out_id = int(choice_out)
                if 0 <= out_id < len(out_ports):
                    out_name = out_ports[out_id]
                    try:
                        outport = mido.open_output(out_name, api='WINDOWS_MM')
                        print(f"监听输出端口: {out_name!r}")
                    except Exception as e:
                        print(f"⚠️ 打开监听输出端口失败：{e}")
                else:
                    print("编号超出范围，跳过监听回放。")

    # 创建 MIDI 文件和轨道
    mid = MidiFile()
    track = MidiTrack()
    mid.tracks.append(track)

    # 设置默认速度 (120 BPM)
    tempo = mido.bpm2tempo(120)
    track.append(mido.MetaMessage('set_tempo', tempo=tempo))

    print(f"\n打开端口: {port_name!r}")
    print("开始录制 MIDI 信号（按回车或 Ctrl+C 停止并保存）\n")

    last_time = time.time()
    message_count = 0
    stop_event = Event()

    def wait_for_enter():
        input("按回车停止录制...\n")
        stop_event.set()

    Thread(target=wait_for_enter, daemon=True).start()

    try:
        # 这里可能会因为驱动/设备问题抛 SystemError
        try:
            with mido.open_input(port_name, api='WINDOWS_MM') as inport:
                while not stop_event.is_set():
                    msg = inport.poll()  # 非阻塞读取，便于响应停止
                    if msg is None:
                        time.sleep(0.01)
                        continue

                    current_time = time.time()
                    delta_seconds = current_time - last_time
                    # 将秒转换为 ticks (默认 ticks_per_beat=480)
                    delta_ticks = int(mido.second2tick(
                        delta_seconds,
                        mid.ticks_per_beat,
                        tempo
                    ))
                    last_time = current_time

                    # 只保存音符和控制器消息（忽略系统消息）
                    if msg.type in ['note_on', 'note_off',
                                    'control_change', 'program_change', 'pitchwheel']:
                        track.append(msg.copy(time=delta_ticks))
                        message_count += 1
                        print(f"[{message_count}] {msg}")
                        if outport:
                            try:
                                outport.send(msg)
                            except Exception as send_err:
                                print(f"⚠️ 回放发送失败: {send_err}")
        except (SystemError, OSError) as e:
            print("\n⚠️ 打开 MIDI 端口失败（WINDOWS_MM）")
            print(f"错误：{e}")
            print("尝试改用默认 API 再打开一次…")
            try:
                with mido.open_input(port_name) as inport:
                    while not stop_event.is_set():
                        msg = inport.poll()
                        if msg is None:
                            time.sleep(0.01)
                            continue

                        current_time = time.time()
                        delta_seconds = current_time - last_time
                        delta_ticks = int(mido.second2tick(
                            delta_seconds,
                            mid.ticks_per_beat,
                            tempo
                        ))
                        last_time = current_time

                        if msg.type in ['note_on', 'note_off',
                                        'control_change', 'program_change', 'pitchwheel']:
                            track.append(msg.copy(time=delta_ticks))
                            message_count += 1
                            print(f"[{message_count}] {msg}")
                            if outport:
                                try:
                                    outport.send(msg)
                                except Exception as send_err:
                                    print(f"⚠️ 回放发送失败: {send_err}")
            except Exception as e2:
                print("\n❌ 默认 API 打开也失败。")
                print(f"错误：{e2}")
                print("可尝试措施：")
                print("  - 确认设备/驱动已就绪，可在别的 MIDI 工具里能正常打开；")
                print("  - 重插设备或更换 USB 口；")
                print("  - 关闭占用该端口的其他应用后重试；")
                return
    except SystemError as e:
        print("\n❌ 打开 MIDI 输入端口失败。")
        print(f"底层错误: {e}")
        print("可能原因：")
        print("  - 设备驱动异常或不完全支持 WinMM；")
        print("  - 设备已被其他程序占用；")
        print("  - 该设备其实并不是标准的 USB-MIDI 设备。")
        return

    except KeyboardInterrupt:
        print("\n\n录制结束！")

    if outport:
        try:
            outport.close()
        except Exception:
            pass

    # 保存结果
    if message_count > 0:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recording_{timestamp}.mid"
        os.makedirs("files", exist_ok=True)
        save_path = os.path.join("files", filename)
        mid.save(save_path)
        print(f"已保存 {message_count} 条 MIDI 消息到: {save_path}")
    else:
        print("没有录制到任何 MIDI 消息，未保存文件。")


def show_menu():
    """显示主菜单"""
    print("\n" + "=" * 40)
    print("      MIDI 工具")
    print("=" * 40)
    print("[1] 录制 MIDI（从钢琴录入并保存）")
    print("[2] 解析 MIDI 文件")
    print("[3] 退出")
    print("=" * 40)


if __name__ == "__main__":
    while True:
        show_menu()
        choice = input("请选择功能: ").strip()

        if choice == '1':
            main()
        elif choice == '2':
            filepath = input("请输入 MIDI 文件路径: ").strip()
            parse_midi_file(filepath)
        elif choice == '3':
            print("再见！")
            break
        else:
            print("无效选择，请重新输入。")
