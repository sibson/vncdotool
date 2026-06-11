from __future__ import annotations

from enum import IntEnum


class Key(IntEnum):
    """keycodes for KeyEvent()."""
    BackSpace = 0xFF08
    Tab = 0xFF09
    Return = 0xFF0D
    Escape = 0xFF1B
    Insert = 0xFF63
    Delete = 0xFFFF
    Home = 0xFF50
    End = 0xFF57
    PageUp = 0xFF55
    PageDown = 0xFF56
    Left = 0xFF51
    Up = 0xFF52
    Right = 0xFF53
    Down = 0xFF54
    F1 = 0xFFBE
    F2 = 0xFFBF
    F3 = 0xFFC0
    F4 = 0xFFC1
    F5 = 0xFFC2
    F6 = 0xFFC3
    F7 = 0xFFC4
    F8 = 0xFFC5
    F9 = 0xFFC6
    F10 = 0xFFC7
    F11 = 0xFFC8
    F12 = 0xFFC9
    F13 = 0xFFCA
    F14 = 0xFFCB
    F15 = 0xFFCC
    F16 = 0xFFCD
    F17 = 0xFFCE
    F18 = 0xFFCF
    F19 = 0xFFD0
    F20 = 0xFFD1
    ShiftLeft = 0xFFE1
    ShiftRight = 0xFFE2
    ControlLeft = 0xFFE3
    ControlRight = 0xFFE4
    MetaLeft = 0xFFE7
    MetaRight = 0xFFE8
    AltLeft = 0xFFE9
    AltRight = 0xFFEA

    Scroll_Lock = 0xFF14
    Sys_Req = 0xFF15
    Num_Lock = 0xFF7F
    Caps_Lock = 0xFFE5
    Pause = 0xFF13
    Super_L = 0xFFEB  # windows-key, apple command key
    Super_R = 0xFFEC  # windows-key, apple command key
    Hyper_L = 0xFFED
    Hyper_R = 0xFFEE

    KP_0 = 0xFFB0
    KP_1 = 0xFFB1
    KP_2 = 0xFFB2
    KP_3 = 0xFFB3
    KP_4 = 0xFFB4
    KP_5 = 0xFFB5
    KP_6 = 0xFFB6
    KP_7 = 0xFFB7
    KP_8 = 0xFFB8
    KP_9 = 0xFFB9
    KP_Enter = 0xFF8D

    ForwardSlash = 0x002F
    BackSlash = 0x005C
    SpaceBar = 0x0020


KEYMAP = {
    "bsp": Key.BackSpace,
    "tab": Key.Tab,
    "return": Key.Return,
    "enter": Key.Return,
    "esc": Key.Escape,
    "ins": Key.Insert,
    "delete": Key.Delete,
    "del": Key.Delete,
    "home": Key.Home,
    "end": Key.End,
    "pgup": Key.PageUp,
    "pgdn": Key.PageDown,
    "left": Key.Left,
    "up": Key.Up,
    "right": Key.Right,
    "down": Key.Down,
    "slash": Key.BackSlash,
    "bslash": Key.BackSlash,
    "fslash": Key.ForwardSlash,
    "spacebar": Key.SpaceBar,
    "space": Key.SpaceBar,
    "sb": Key.SpaceBar,
    "f1": Key.F1,
    "f2": Key.F2,
    "f3": Key.F3,
    "f4": Key.F4,
    "f5": Key.F5,
    "f6": Key.F6,
    "f7": Key.F7,
    "f8": Key.F8,
    "f9": Key.F9,
    "f10": Key.F10,
    "f11": Key.F11,
    "f12": Key.F12,
    "f13": Key.F13,
    "f14": Key.F14,
    "f15": Key.F15,
    "f16": Key.F16,
    "f17": Key.F17,
    "f18": Key.F18,
    "f19": Key.F19,
    "f20": Key.F20,
    "lshift": Key.ShiftLeft,
    "shift": Key.ShiftLeft,
    "rshift": Key.ShiftRight,
    "lctrl": Key.ControlLeft,
    "ctrl": Key.ControlLeft,
    "rctrl": Key.ControlRight,
    "lmeta": Key.MetaLeft,
    "meta": Key.MetaLeft,
    "rmeta": Key.MetaRight,
    "lalt": Key.AltLeft,
    "alt": Key.AltLeft,
    "ralt": Key.AltRight,
    "scrlk": Key.Scroll_Lock,
    "sysrq": Key.Sys_Req,
    "numlk": Key.Num_Lock,
    "caplk": Key.Caps_Lock,
    "pause": Key.Pause,
    "lsuper": Key.Super_L,
    "super": Key.Super_L,
    "rsuper": Key.Super_R,
    "lhyper": Key.Hyper_L,
    "hyper": Key.Hyper_L,
    "rhyper": Key.Hyper_R,
    "kp0": Key.KP_0,
    "kp1": Key.KP_1,
    "kp2": Key.KP_2,
    "kp3": Key.KP_3,
    "kp4": Key.KP_4,
    "kp5": Key.KP_5,
    "kp6": Key.KP_6,
    "kp7": Key.KP_7,
    "kp8": Key.KP_8,
    "kp9": Key.KP_9,
    "kpenter": Key.KP_Enter,
    "minus": ord('-'),  # Literal `-` will get split while decoding
}
