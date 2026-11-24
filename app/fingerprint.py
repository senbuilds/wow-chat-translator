"""机器码：只用来防止同一台电脑反复领免费试用。

读三样东西，各自在本机打码（SHA-256）后才发给服务器，原值不出这台电脑：
  board    主板 UUID（SMBIOS 表里的系统 UUID，重装系统也不变）
  machine  Windows 机器 ID（注册表 MachineGuid，重装系统会变）
  disk     系统盘的硬件序列号（换硬盘才会变）
另外顺带看一眼是不是虚拟机（服务器对虚拟机单独限量）。

都直接调 Windows 自带的接口，不需要管理员权限，不启动任何别的程序。读不到的那一项就不带。
客户端是开源的，这些值能被人改掉；真正的把关在服务器（IP、人机验证、每日总量）。
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import re
import uuid

SALT = "chatbridge-fp-v1"
# 厂商没好好填、很多机器都一样的 UUID：当成没有
BAD_UUIDS = {"00000000-0000-0000-0000-000000000000", "ffffffff-ffff-ffff-ffff-ffffffffffff",
             "03000200-0400-0500-0006-000700080009", "00020003-0004-0005-0006-000700080009"}
VM_WORDS = ("vmware", "virtualbox", "innotek", "qemu", "kvm", "xen", "parallels", "bochs", "virtual machine",
            "hyper-v", "bhyve", "amazon ec2", "google compute", "openstack")


def _hash(kind, raw):
    return hashlib.sha256(("%s|%s|%s" % (SALT, kind, raw)).encode("utf-8")).hexdigest()


def _smbios():
    """返回 (系统 UUID, 厂商, 型号)；读不到就是 (None, "", "")。"""
    try:
        k32 = ctypes.windll.kernel32
        sig = 0x52534D42                                   # 'RSMB'
        size = k32.GetSystemFirmwareTable(sig, 0, None, 0)
        if not size:
            return None, "", ""
        buf = ctypes.create_string_buffer(size)
        if k32.GetSystemFirmwareTable(sig, 0, buf, size) != size:
            return None, "", ""
        data = buf.raw
        length = int.from_bytes(data[4:8], "little")
        table, i = data[8:8 + length], 0
        while i + 4 <= len(table):
            kind, slen = table[i], table[i + 1]
            if slen < 4:
                break
            end = i + slen                                  # 格式化区之后是以两个 0 结尾的字符串区
            j = end
            while j + 1 < len(table) and not (table[j] == 0 and table[j + 1] == 0):
                j += 1
            strings = table[end:j].split(b"\0")
            if kind == 1 and slen >= 0x19:
                def s(idx):
                    n = table[i + idx]
                    return strings[n - 1].decode("latin-1", "replace").strip() if 0 < n <= len(strings) else ""
                raw = bytes(table[i + 8:i + 24])
                uid = str(uuid.UUID(bytes_le=raw)).lower()
                return (None if uid in BAD_UUIDS else uid), s(4), s(5)
            if kind == 127:
                break
            i = j + 2
    except Exception:
        pass
    return None, "", ""


def _machine_guid():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            value = str(winreg.QueryValueEx(k, "MachineGuid")[0]).strip().lower()
            return value or None
    except Exception:
        return None


class _STORAGE_PROPERTY_QUERY(ctypes.Structure):
    _fields_ = [("PropertyId", ctypes.c_int), ("QueryType", ctypes.c_int), ("Extra", ctypes.c_ubyte * 1)]


def _system_disk_serial():
    """系统盘（C: 所在的物理盘）的硬件序列号。"""
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = wt.HANDLE
        INVALID = wt.HANDLE(-1).value
        # 先找 C: 在第几块物理盘上
        vol = k32.CreateFileW(r"\\.\C:", 0, 3, None, 3, 0, None)
        disk_no = 0
        if vol and vol != INVALID:
            out = ctypes.create_string_buffer(64)
            got = wt.DWORD()
            if k32.DeviceIoControl(wt.HANDLE(vol), 0x002D1080, None, 0, out, 64, ctypes.byref(got), None):
                disk_no = int.from_bytes(out.raw[4:8], "little")   # STORAGE_DEVICE_NUMBER.DeviceNumber
            k32.CloseHandle(wt.HANDLE(vol))
        h = k32.CreateFileW(r"\\.\PhysicalDrive%d" % disk_no, 0, 3, None, 3, 0, None)
        if not h or h == INVALID:
            return None
        try:
            query = _STORAGE_PROPERTY_QUERY(0, 0)               # StorageDeviceProperty, PropertyStandardQuery
            out = ctypes.create_string_buffer(4096)
            got = wt.DWORD()
            if not k32.DeviceIoControl(wt.HANDLE(h), 0x002D1400, ctypes.byref(query), ctypes.sizeof(query),
                                       out, 4096, ctypes.byref(got), None):
                return None
            raw = out.raw[:got.value]
            offset = int.from_bytes(raw[24:28], "little")        # STORAGE_DEVICE_DESCRIPTOR.SerialNumberOffset
            if not offset or offset >= len(raw):
                return None
            serial = raw[offset:raw.index(b"\0", offset)].decode("latin-1", "replace")
            serial = re.sub(r"\s+", "", serial).strip(".").lower()
            return serial if len(serial) >= 4 and len(set(serial)) > 2 else None
        finally:
            k32.CloseHandle(wt.HANDLE(h))
    except Exception:
        return None


def collect():
    """返回 ({"board"/"machine"/"disk": 打过码的值}, 是不是虚拟机)。"""
    board, maker, model = _smbios()
    parts = {}
    if board:
        parts["board"] = _hash("board", board)
    guid = _machine_guid()
    if guid:
        parts["machine"] = _hash("machine", guid)
    disk = _system_disk_serial()
    if disk:
        parts["disk"] = _hash("disk", disk)
    text = ("%s %s" % (maker, model)).lower()
    vm = any(w in text for w in VM_WORDS)
    return parts, vm


if __name__ == "__main__":
    fp, vm = collect()
    print("parts:", sorted(fp), "vm:", vm)
