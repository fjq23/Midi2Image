import os
import sys
import mido
from mido import MidiFile


def midi_to_frame_list(filepath):
    """
    解析 MIDI 文件为 Python 列表，每个元素代表一条按时间排序的 MIDI 帧。
    帧字段包括秒、tick、类型和常用消息字段（不存在的字段会是 None）。
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(filepath)

    mid = MidiFile(filepath)
    tempo = 500000  # 默认 120 BPM
    tick_acc = 0
    frames = []

    # 将多轨合并，方便按时间顺序遍历
    for msg in mido.merge_tracks(mid.tracks):
        tick_acc += msg.time
        time_s = mido.tick2second(tick_acc, mid.ticks_per_beat, tempo)

        if msg.type == "set_tempo":
            tempo = msg.tempo

        if msg.type in ["note_on", "note_off", "control_change",
                        "program_change", "pitchwheel", "set_tempo"]:
            frames.append({
                "time_s": time_s,
                "tick": tick_acc,
                "type": msg.type,
                "channel": getattr(msg, "channel", None),
                "note": getattr(msg, "note", None),
                "velocity": getattr(msg, "velocity", None),
                "control": getattr(msg, "control", None),
                "value": getattr(msg, "value", None),
                "program": getattr(msg, "program", None),
                "pitch": getattr(msg, "pitch", None),
                "tempo": getattr(msg, "tempo", None),
            })
    return frames


def _cli():
    if len(sys.argv) < 2:
        print("用法: python midi_parser.py <midi_file>")
        sys.exit(1)
    filepath = sys.argv[1]
    frames = midi_to_frame_list(filepath)
    print(f"帧数量: {len(frames)}")
    for i, frame in enumerate(frames[:10], 1):
        print(f"[{i}] {frame}")
    if len(frames) > 10:
        print("...（仅展示前 10 帧）")


if __name__ == "__main__":
    _cli()
