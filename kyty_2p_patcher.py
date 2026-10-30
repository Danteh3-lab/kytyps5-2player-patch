# Builds kyty_emulator_2p.exe: local 2-player (second user + second pad) for KytyPS5 / UFC 6.
# Usage: python patch2p.py <original exe> <output exe> <notes-listing out>
import sys, re, struct
from keystone import Ks, KS_ARCH_X86, KS_MODE_64
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

SRC, DST, LST = sys.argv[1], sys.argv[2], sys.argv[3]
data = bytearray(open(SRC, 'rb').read())
BASE = 0x140000000
ks = Ks(KS_ARCH_X86, KS_MODE_64)
cs = Cs(CS_ARCH_X86, CS_MODE_64)

# ---------------------------------------------------------------- PE layout
e = struct.unpack_from('<I', data, 0x3c)[0]
nsec_off = e + 6
nsec = struct.unpack_from('<H', data, nsec_off)[0]
optsz = struct.unpack_from('<H', data, e + 20)[0]
opt = e + 24
secs = []
for i in range(nsec):
    so = opt + optsz + 40 * i
    name = bytes(data[so:so + 8]).rstrip(b'\0').decode()
    vsz, va, rsz, rp = struct.unpack_from('<IIII', data, so + 8)
    secs.append((name, va, vsz, rp, rsz))
assert nsec == 8 and secs[-1][0] == '.reloc', 'unexpected exe (wrong build?)'

def va2off(v):
    r = v - BASE
    for n, va, vsz, rp, rsz in secs:
        if va <= r < va + rsz:
            return rp + (r - va)
    raise ValueError(hex(v))

NEWSEC_RVA = 0x3bcc000
NEWSEC_RAW = len(data)
NEWSEC_SIZE = 0x1000
CODE = BASE + NEWSEC_RVA
DATA = CODE + 0x800

# ---------------------------------------------------------------- symbols
S = dict(
    G=0x143937c90,        # Controller* g_controller
    CFG=0x143970fb0,      # Config*; +0x28 = user_id
    LOCK=0x1417b13b0,     # IAT: mutex lock
    UNLOCK=0x1417b16e0,   # IAT: mutex unlock
    CONVERT=0x140196ed0,  # (PadData* out, State* st, u8 connected, u32 connected_count)
    NEW=0x140fb28f8,      # operator new
    CTOR=0x140fe0a10,     # Controller::Controller
    GETUSER=0x1402bfca0,  # returns cfg user_id
    EVFLAG=0x14393cbc0,   # UserServiceGetEvent "already sent" flag (now a counter)
    LOGHOOK=0x14392d408,
    D_G2=DATA + 0x00,     # Controller* for player 2
    D_P2ID=DATA + 0x08,   # host device id bound to player 2
    D_P2CL=DATA + 0x0c,   # 1 = a device is bound to player 2
    D_NAME=DATA + 0x10,   # "Player 2"
)

# ---------------------------------------------------------------- mini assembler
def assemble(lines, base, extra=None):
    labels = {}
    names = {l.split(';')[0].strip()[:-1] for l in lines if l.split(';')[0].strip().endswith(':')}
    lines = [re.sub(r'^(\s*(?:j\w+|call)\s+)(\w+)\s*$', lambda m: m.group(1) + ('{%s}' % m.group(2) if m.group(2) in names else m.group(2)), l) for l in lines]
    for _ in range(20):
        addr, out, newl, listing = base, b'', {}, []
        for raw in lines:
            ln = raw.split(';')[0].strip()
            if not ln:
                continue
            if ln.endswith(':'):
                newl[ln[:-1]] = addr
                continue
            env = dict(S, **(extra or {}), **labels)
            txt = re.sub(r'\{(\w+)\}', lambda m: hex(env.get(m.group(1), addr)), ln)
            m = re.search(r'RIP\(([^)]+)\)', txt)
            if m:
                tgt = int(m.group(1), 0)
                enc, _ = ks.asm(txt.replace(m.group(0), 'rip + 0x7fffffff'), addr)
                L = len(enc)
                disp = tgt - (addr + L)
                rep = 'rip + %#x' % disp if disp >= 0 else 'rip - %#x' % -disp
                enc, _ = ks.asm(txt.replace(m.group(0), rep), addr)
                assert len(enc) == L, txt
            else:
                try:
                    enc, _ = ks.asm(txt, addr)
                except Exception as ex:
                    raise RuntimeError('asm failed: %r -> %r: %s' % (ln, txt, ex))
            enc = bytes(enc)
            listing.append((addr, enc, ln))
            out += enc
            addr += len(enc)
        if newl == labels:
            return out, labels, listing
        labels = newl
    raise RuntimeError('labels did not converge')

# ---------------------------------------------------------------- new code
code_src = r'''
; --- create a second Controller right after g_controller is created
h_create:
  mov qword ptr [RIP({G})], rcx
  mov ecx, 0x1790
  call {NEW}
  mov rcx, rax
  call {CTOR}
  mov qword ptr [RIP({D_G2})], rax
  mov rcx, qword ptr [RIP({G})]
  jmp 0x140fdfa8d

; --- rcx=this, edx=host device id. Leaf; may replace rcx with player 2's Controller.
route:
  test edx, edx
  js route_ret
  cmp rcx, qword ptr [RIP({G})]
  jne route_ret
  cmp edx, dword ptr [rcx + 0x28]
  je route_ret
  push rax
  mov rax, qword ptr [RIP({D_G2})]
  test rax, rax
  jz route_pop
  cmp dword ptr [RIP({D_P2CL})], 0
  je route_claim
  cmp edx, dword ptr [RIP({D_P2ID})]
  jne route_pop
  mov rcx, rax
  jmp route_pop
route_claim:
  cmp dword ptr [rcx + 0x28], 0
  jl route_pop
  call claim
  mov rcx, rax
route_pop:
  pop rax
route_ret:
  ret

; --- rax=player 2 Controller, edx=device id
claim:
  mov dword ptr [RIP({D_P2ID})], edx
  mov dword ptr [RIP({D_P2CL})], 1
  mov dword ptr [rax + 0x28], edx
  mov byte ptr [rax + 0x2c], 1
  inc dword ptr [rax + 0x30]
  ret

h_setaxis:
  call route
  push rbp
  push r15
  push r14
  jmp 0x14126f275
h_setbtn:
  call route
  push rbp
  push r14
  push rsi
  push rdi
  jmp 0x14126f045
h_sensor:
  call route
  push rbp
  push r15
  push r14
  jmp 0x14126fab5
h_sensor2:
  call route
  push rbp
  push r15
  push r14
  jmp 0x14126fe05
h_set5:
  call route
  push rbp
  push r14
  push rsi
  push rdi
  jmp 0x14126f885

; --- device connected: bind it to player 2 if player 1 already has a gamepad
h_conn:
  test edx, edx
  js conn_go
  cmp rcx, qword ptr [RIP({G})]
  jne conn_go
  cmp dword ptr [rcx + 0x28], 0
  jl conn_go
  cmp edx, dword ptr [rcx + 0x28]
  je conn_go
  cmp dword ptr [RIP({D_P2CL})], 0
  jne conn_go
  push rax
  mov rax, qword ptr [RIP({D_G2})]
  test rax, rax
  jz conn_pop
  call claim
conn_pop:
  pop rax
conn_go:
  push rbp
  push r15
  push r14
  jmp 0x140fe1615

; --- device removed: unbind player 2
h_disc:
  cmp rcx, qword ptr [RIP({G})]
  jne disc_go
  cmp dword ptr [RIP({D_P2CL})], 0
  je disc_go
  cmp edx, dword ptr [RIP({D_P2ID})]
  jne disc_go
  mov dword ptr [RIP({D_P2CL})], 0
  mov dword ptr [RIP({D_P2ID})], -1
  push rax
  mov rax, qword ptr [RIP({D_G2})]
  mov byte ptr [rax + 0x2c], 0
  mov dword ptr [rax + 0x28], -1
  pop rax
disc_go:
  push rbp
  push rsi
  push rdi
  sub rsp, 0x30
  jmp 0x14126ef67

; --- Controller::Open(rcx=this, edx=user, r8d=type, r9d=index) -> handle 2 for user_id+1
h_open:
  mov r10, qword ptr [RIP({CFG})]
  mov r10d, dword ptr [r10 + 0x28]
  inc r10d
  cmp edx, r10d
  jne open_go
  mov r11, qword ptr [RIP({D_G2})]
  mov eax, 0x80920005
  test r11, r11
  jz open_ret
  cmp dword ptr [rcx + 8], 0
  je open_ret
  mov eax, 0x80920001
  or r8d, r9d
  jnz open_ret
  mov eax, 0x80920004
  cmp dword ptr [r11 + 8], 2
  je open_ret
  mov dword ptr [r11 + 8], 2
  mov eax, 2
open_ret:
  ret
open_go:
  push rbp
  push r14
  push rsi
  push rdi
  jmp 0x1410d5ec5

; --- Controller::GetHandle(rcx=this, edx=user, r8d=type, r9d=index)
h_geth:
  mov r10, qword ptr [RIP({CFG})]
  mov r10d, dword ptr [r10 + 0x28]
  inc r10d
  cmp edx, r10d
  jne geth_go
  mov r11, qword ptr [RIP({D_G2})]
  mov eax, 0x80920005
  test r11, r11
  jz geth_ret
  mov eax, 0x80920008
  cmp dword ptr [r11 + 8], 2
  jne geth_ret
  or r8d, r9d
  jnz geth_ret
  mov eax, 2
geth_ret:
  ret
geth_go:
  push rbp
  push r14
  push rsi
  push rdi
  jmp 0x141271005

; --- scePadClose(edi=handle)  [SysV]
h_close:
  cmp edi, 2
  jne close_go
  mov rax, qword ptr [RIP({D_G2})]
  test rax, rax
  jz close_e3
  cmp dword ptr [rax + 8], 2
  jne close_e3
  mov dword ptr [rax + 8], 1
  xor eax, eax
  ret
close_e3:
  mov eax, 0x80920003
  ret
close_go:
  push rbp
  sub rsp, 0x2b0
  jmp 0x141271308

; --- read player 2 state into PadData at rsi. eax = 0 or error.  [called from SysV stubs]
read_g2:
  push rbx
  push r12
  push r13
  sub rsp, 0x88
  mov rbx, qword ptr [RIP({D_G2})]
  mov eax, 0x80920005
  test rbx, rbx
  jz rg_out
  cmp dword ptr [rbx + 8], 0
  je rg_out
  mov eax, 0x80920003
  cmp dword ptr [rbx + 8], 2
  jne rg_out
  mov rcx, qword ptr [rbx]
  call qword ptr [RIP({LOCK})]
  movzx r12d, byte ptr [rbx + 0x2c]
  mov r13d, dword ptr [rbx + 0x30]
  vmovups ymm0, ymmword ptr [rbx + 0x50]
  vmovups ymmword ptr [rsp + 0x20], ymm0
  vmovups ymm0, ymmword ptr [rbx + 0x70]
  vmovups ymmword ptr [rsp + 0x40], ymm0
  vmovups ymm0, ymmword ptr [rbx + 0x88]
  vmovups ymmword ptr [rsp + 0x58], ymm0
  vzeroupper
  mov rcx, qword ptr [rbx]
  call qword ptr [RIP({UNLOCK})]
  mov rcx, rsi
  lea rdx, [rsp + 0x20]
  mov r8d, r12d
  mov r9d, r13d
  call {CONVERT}
  xor eax, eax
rg_out:
  add rsp, 0x88
  pop r13
  pop r12
  pop rbx
  ret

; --- scePadReadState(edi=handle, rsi=data)  [SysV]
h_rstate:
  cmp edi, 2
  jne rs_go
  mov eax, 0x80920001
  test rsi, rsi
  jz rs_ret
  call read_g2
rs_ret:
  ret
rs_go:
  push r15
  push r14
  push rbx
  jmp 0x141271945

; --- scePadRead(edi=handle, rsi=data, edx=num)  [SysV]  -> one sample for player 2
h_read:
  cmp edi, 2
  jne rd_go
  mov eax, 0x80920001
  test rsi, rsi
  jz rd_ret
  lea ecx, [rdx - 1]
  cmp ecx, 63
  ja rd_ret
  mov rdi, rsi
  mov ecx, 0x78
  xor eax, eax
  rep stosb byte ptr [rdi], al
  call read_g2
  test eax, eax
  jnz rd_ret
  mov eax, 1
rd_ret:
  ret
rd_go:
  push rbp
  push r15
  push r14
  jmp 0x140196b45

; --- scePadGetControllerInformation(edi=handle, rsi=info)  [SysV]
h_info:
  cmp edi, 2
  jne info_go
  mov rdx, qword ptr [RIP({D_G2})]
  mov eax, 0x80920005
  test rdx, rdx
  jz info_ret
  mov eax, 0x80920003
  cmp dword ptr [rdx + 8], 2
  jne info_ret
  mov eax, 0x80920001
  test rsi, rsi
  jz info_ret
  vxorps xmm0, xmm0, xmm0
  vmovups xmmword ptr [rsi + 0xc], xmm0
  movabs rax, 0x3af0780423370a4
  mov qword ptr [rsi], rax
  mov word ptr [rsi + 8], 0x1e1e
  mov byte ptr [rsi + 0xa], 0
  mov ecx, dword ptr [rdx + 0x30]
  mov eax, 0xff
  cmp ecx, eax
  cmovl eax, ecx
  mov byte ptr [rsi + 0xb], al
  mov al, byte ptr [rdx + 0x2c]
  mov byte ptr [rsi + 0xc], al
  xor eax, eax
info_ret:
  ret
info_go:
  push rbp
  push r14
  push rbx
  sub rsp, 0x20
  jmp 0x140bce078

; --- sceUserServiceGetUserName(edi=user, rsi=buf, rdx=size)  [SysV]
h_name:
  mov rax, qword ptr [RIP({CFG})]
  mov eax, dword ptr [rax + 0x28]
  inc eax
  cmp edi, eax
  jne name_go
  mov eax, 0x80960005
  test rsi, rsi
  jz name_ret
  test rdx, rdx
  jz name_ret
  lea r8, [RIP({D_NAME})]
  xor ecx, ecx
name_loop:
  lea rax, [rcx + 1]
  cmp rax, rdx
  jae name_term
  movzx eax, byte ptr [r8 + rcx]
  test al, al
  jz name_term
  mov byte ptr [rsi + rcx], al
  inc rcx
  jmp name_loop
name_term:
  mov byte ptr [rsi + rcx], 0
  xor eax, eax
name_ret:
  ret
name_go:
  sub rsp, 0x28
  mov r9, qword ptr [RIP({CFG})]
  jmp 0x140c55b7b

; --- sceUserServiceGetUserNumber(edi=user, rsi=out)  [SysV]
h_num:
  mov rax, qword ptr [RIP({CFG})]
  mov eax, dword ptr [rax + 0x28]
  inc eax
  cmp edi, eax
  jne num_go
  mov eax, 0x80960005
  test rsi, rsi
  jz num_ret
  mov dword ptr [rsi], 2
  xor eax, eax
num_ret:
  ret
num_go:
  sub rsp, 0x28
  mov rax, qword ptr [RIP({LOGHOOK})]
  jmp 0x140c55c2b

; ================= player 2 output (vibration, light bar, adaptive triggers, motion)

; --- leaf: rcx = player-2 Controller, eax = 0 if its pad is open, else pad error
p2chk:
  mov rcx, qword ptr [RIP({D_G2})]
  mov eax, 0x80920005
  test rcx, rcx
  jz p2chk_ret
  mov eax, 0x80920003
  cmp dword ptr [rcx + 8], 2
  jne p2chk_ret
  xor eax, eax
p2chk_ret:
  ret

; --- Controller handle check (rcx=this, edx=handle): accept handle 2 when player 2 is open
h_check:
  cmp edx, 2
  jne hchk_go
  cmp rcx, qword ptr [RIP({G})]
  jne hchk_go
  jmp p2chk
hchk_go:
  push rsi
  push rdi
  push rbx
  sub rsp, 0x20
  jmp 0x140fd5127

; --- scePadSetVibration(edi=handle, rsi=param)  [SysV]
h_vib:
  cmp edi, 2
  jne vib_go
  call p2chk
  test eax, eax
  jnz vib_ret
  mov eax, 0x80920001
  test rsi, rsi
  jz vib_ret
  sub rsp, 0x28
  mov dl, byte ptr [rsi]
  mov r8b, byte ptr [rsi + 1]
  call 0x140fd5170
  add rsp, 0x28
  xor eax, eax
vib_ret:
  ret
vib_go:
  push rbp
  sub rsp, 0x2c0
  jmp 0x140fd4f38

; --- scePadSetLightBar(edi=handle, rsi=rgb)  [SysV]
h_lb:
  cmp edi, 2
  jne lb_go
  call p2chk
  test eax, eax
  jnz lb_ret
  mov eax, 0x80920001
  test rsi, rsi
  jz lb_ret
  sub rsp, 0x28
  mov dl, byte ptr [rsi]
  mov r8b, byte ptr [rsi + 1]
  mov r9b, byte ptr [rsi + 2]
  call 0x141270a70
  add rsp, 0x28
  xor eax, eax
lb_ret:
  ret
lb_go:
  sub rsp, 0x28
  mov rax, qword ptr [RIP({LOGHOOK})]
  jmp 0x141271a1b

; --- scePadSetTriggerEffect(edi=handle, rsi=param)  [SysV]
h_trig:
  cmp edi, 2
  jne trig_go
  call p2chk
  test eax, eax
  jnz trig_ret
  mov eax, 0x80920001
  test rsi, rsi
  jz trig_ret
  sub rsp, 0x28
  mov rdx, rsi
  call 0x141270b60
  add rsp, 0x28
  xor ecx, ecx
  test al, al
  mov eax, 0x80920001
  cmovne eax, ecx
trig_ret:
  ret
trig_go:
  sub rsp, 0x28
  mov rax, qword ptr [RIP({LOGHOOK})]
  jmp 0x141271a8b

; --- scePadGetTriggerEffectState(edi=handle, rsi=out)  [SysV]
h_tstate:
  cmp edi, 2
  jne tst_go
  call p2chk
  test eax, eax
  jnz tst_ret
  mov eax, 0x80920001
  test rsi, rsi
  jz tst_ret
  sub rsp, 0x28
  mov rdx, rsi
  call 0x141270f80
  add rsp, 0x28
  xor eax, eax
tst_ret:
  ret
tst_go:
  push rbp
  push rbx
  sub rsp, 0x2a8
  jmp 0x141271af9

; --- scePadSetMotionSensorState(edi=handle, sil=enable)  [SysV]
h_motion:
  cmp edi, 2
  jne mot_go
  call p2chk
  test eax, eax
  jnz mot_ret
  sub rsp, 0x28
  mov edx, esi
  call 0x141270420
  add rsp, 0x28
  xor eax, eax
mot_ret:
  ret
mot_go:
  push rbp
  push rbx
  sub rsp, 0x2a8
  jmp 0x1412714c9

; --- scePadResetOrientation(edi=handle)  [SysV]
h_orient:
  cmp edi, 2
  jne ori_go
  call p2chk
  test eax, eax
  jnz ori_ret
  sub rsp, 0x28
  call 0x141270650
  add rsp, 0x28
  xor eax, eax
ori_ret:
  ret
ori_go:
  sub rsp, 0x28
  mov rax, qword ptr [RIP({LOGHOOK})]
  jmp 0x14127189b

; --- DualSense HID rumble (ecx=device id): it drives one global DualSense session, keep it
;     on player 1. For player 2's device return "not handled" so SDL rumbles that pad itself.
h_dsr:
  cmp dword ptr [RIP({D_P2CL})], 0
  je dsr_go
  cmp ecx, dword ptr [RIP({D_P2ID})]
  jne dsr_go
  xor eax, eax
  ret
dsr_go:
  push r14
  push rsi
  push rdi
  push rbp
  jmp 0x140fd55a5
'''

# user-id checks "cmp [rcx+0x28],edi ; jne +d8" in the other UserService getters
CHECK_SITES = [0x140c55ca1, 0x140c55d21, 0x140c55d81, 0x140c55de1,
               0x140c55e41, 0x140c55ea1, 0x140c55f01, 0x140c55f61]
for i, site in enumerate(CHECK_SITES):
    b = bytes(data[va2off(site):va2off(site) + 5])
    assert b[:4] == bytes.fromhex('39792875'), (hex(site), b.hex())
    code_src += '''
chk%d:
  mov r11d, dword ptr [rcx + 0x28]
  cmp edi, r11d
  je chk%d_ok
  inc r11d
  cmp edi, r11d
  je chk%d_ok
  add qword ptr [rsp], %#x
chk%d_ok:
  ret
''' % (i, i, i, b[4], i)

code, L, code_listing = assemble(code_src.splitlines(), CODE)
assert len(code) <= 0x800, hex(len(code))

# ---------------------------------------------------------------- patches into existing code
patches = []   # (va, new bytes, description)

def hook(va, target, length, expect, desc):
    off = va2off(va)
    orig = bytes(data[off:off + length])
    assert orig == bytes.fromhex(expect), (hex(va), orig.hex(), expect)
    enc, _ = ks.asm('jmp %#x' % target, va)
    enc = bytes(enc)
    assert len(enc) == 5
    patches.append((va, enc + b'\x90' * (length - 5), desc))

hook(0x140fdfa86, L['h_create'], 7, '48890d03829502', 'g_controller creation: also create player-2 Controller')
hook(0x14126f270, L['h_setaxis'], 5, '5541574156', 'Controller SetAxis: route player-2 device')
hook(0x14126f040, L['h_setbtn'], 5, '5541565657', 'Controller SetButton: route player-2 device')
hook(0x14126fab0, L['h_sensor'], 5, '5541574156', 'Controller touch/sensor setter: route player-2 device')
hook(0x14126fe00, L['h_sensor2'], 5, '5541574156', 'Controller DualSense setter: route player-2 device')
hook(0x14126f880, L['h_set5'], 5, '5541565657', 'Controller setter (0x14126f880): route player-2 device')
hook(0x140fe1610, L['h_conn'], 5, '5541574156', 'Controller device connected: bind 2nd gamepad to player 2')
hook(0x14126ef60, L['h_disc'], 7, '5556574883ec30', 'Controller device removed: unbind player 2')
hook(0x1410d5ec0, L['h_open'], 5, '5541565657', 'Controller::Open: user_id+1 -> handle 2')
hook(0x141271000, L['h_geth'], 5, '5541565657', 'Controller::GetHandle: user_id+1 -> handle 2')
hook(0x141271300, L['h_close'], 8, '554881ecb0020000', 'scePadClose: handle 2')
hook(0x141271940, L['h_rstate'], 5, '4157415653', 'scePadReadState: handle 2 reads player-2 Controller')
hook(0x140196b40, L['h_read'], 5, '5541574156', 'scePadRead: handle 2 reads player-2 Controller')
hook(0x140bce070, L['h_info'], 8, '554156534883ec20', 'scePadGetControllerInformation: handle 2')
hook(0x140fd5120, L['h_check'], 7, '5657534883ec20', 'Controller handle check: accept handle 2 when player 2 is open')
hook(0x140fd4f30, L['h_vib'], 8, '554881ecc0020000', 'scePadSetVibration: handle 2 -> player-2 Controller')
hook(0x141271a10, L['h_lb'], 11, '4883ec28488b05edb96b02', 'scePadSetLightBar: handle 2 -> player-2 Controller')
hook(0x141271a80, L['h_trig'], 11, '4883ec28488b057db96b02', 'scePadSetTriggerEffect: handle 2 -> player-2 Controller')
hook(0x141271af0, L['h_tstate'], 9, '55534881eca8020000', 'scePadGetTriggerEffectState: handle 2 -> player-2 Controller')
hook(0x1412714c0, L['h_motion'], 9, '55534881eca8020000', 'scePadSetMotionSensorState: handle 2 -> player-2 Controller')
hook(0x141271890, L['h_orient'], 11, '4883ec28488b056dbb6b02', 'scePadResetOrientation: handle 2 -> player-2 Controller')
hook(0x140fd55a0, L['h_dsr'], 5, '4156565755', 'DualSense HID rumble: skip for player 2 device (SDL rumble instead)')
hook(0x140c55b70, L['h_name'], 11, '4883ec284c8b0d35b4d102', 'sceUserServiceGetUserName: "Player 2" for user_id+1')
hook(0x140c55c20, L['h_num'], 11, '4883ec28488b05dd77cd02', 'sceUserServiceGetUserNumber: 2 for user_id+1')

for i, site in enumerate(CHECK_SITES):
    enc, _ = ks.asm('call %#x' % L['chk%d' % i], site)
    patches.append((site, bytes(enc), 'UserService getter user check: also accept user_id+1'))

def inplace(va, end, src, expect_prefix, desc):
    off = va2off(va)
    orig = bytes(data[off:off + (end - va)])
    assert orig.startswith(bytes.fromhex(expect_prefix)), (hex(va), orig.hex())
    enc, _, lst = assemble(src.splitlines(), va)
    assert len(enc) <= end - va, (hex(va), len(enc), end - va)
    patches.append((va, enc + b'\x90' * (end - va - len(enc)), desc))
    code_listing.extend([(0, b'', '; ---- in place @ %#x' % va)] + lst)

inplace(0x140c55b05, 0x140c55b27, r'''
  mov rax, qword ptr [RIP({CFG})]
  mov eax, dword ptr [rax + 0x28]
  mov dword ptr [rdi], eax
  inc eax
  mov dword ptr [rdi + 4], eax
  mov qword ptr [rdi + 8], -1
  xor eax, eax
  add rsp, 0x28
  ret
''', '488b05a4b4d102', 'sceUserServiceGetLoginUserIdList: {user_id, user_id+1, -1, -1}')

inplace(0x140c55a75, 0x140c55aa4, r'''
  movzx ecx, byte ptr [RIP({EVFLAG})]
  mov eax, 0x80960007
  cmp ecx, 2
  jae ev_done
  inc byte ptr [RIP({EVFLAG})]
  mov dword ptr [rdi], 0
  call {GETUSER}
  add eax, ecx
  mov dword ptr [rdi + 4], eax
  xor eax, eax
ev_done:
  add rsp, 0x28
  ret
''', 'b807009680', 'sceUserServiceGetEvent: Login events for user_id, then user_id+1')

# ---------------------------------------------------------------- sanity: new code never returns into a replaced range
for ins in cs.disasm(code, CODE):
    if ins.mnemonic.startswith('j') or ins.mnemonic == 'call':
        try:
            t = int(ins.op_str, 16)
        except ValueError:
            continue
        for va, new, desc in patches:
            assert not (va < t < va + len(new)), ('new code jumps into patched bytes', hex(ins.address), hex(t), desc)

# ---------------------------------------------------------------- sanity: no branch lands inside a replaced range
def func_bounds(va):
    _, pva, pvsz, prp, _ = [s for s in secs if s[0] == '.pdata'][0]
    for i in range(pvsz // 12):
        b, en, _u = struct.unpack_from('<III', data, prp + 12 * i)
        if b and BASE + b <= va < BASE + en:
            return BASE + b, BASE + en
    return None

for va, new, desc in patches:
    fb = func_bounds(va)
    if not fb:
        continue
    lo, hi = fb
    off = va2off(lo)
    for ins in cs.disasm(bytes(data[off:off + (hi - lo)]), lo):
        if ins.mnemonic.startswith('j') or ins.mnemonic == 'call':
            try:
                t = int(ins.op_str, 16)
            except ValueError:
                continue
            if va <= ins.address < va + len(new):
                continue
            assert not (va < t < va + len(new)), ('branch into patched range', hex(ins.address), hex(t), desc)

# ---------------------------------------------------------------- write
records = []
for va, new, desc in patches:
    off = va2off(va)
    records.append((va, bytes(data[off:off + len(new)]), new, desc))
    data[off:off + len(new)] = new

sec = bytearray(NEWSEC_SIZE)
sec[0:len(code)] = code
d0 = DATA - CODE
sec[d0 + 0x08:d0 + 0x0c] = struct.pack('<i', -1)
sec[d0 + 0x10:d0 + 0x19] = b'Player 2\0'
data += sec

hdr = opt + optsz + 40 * nsec
assert bytes(data[hdr:hdr + 40]) == bytes(40)
data[hdr:hdr + 40] = struct.pack('<8sIIIIIIHHI', b'.kyty2p', NEWSEC_SIZE, NEWSEC_RVA, NEWSEC_SIZE,
                                 NEWSEC_RAW, 0, 0, 0, 0, 0xE0000060)
struct.pack_into('<H', data, nsec_off, nsec + 1)
struct.pack_into('<I', data, opt + 56, NEWSEC_RVA + NEWSEC_SIZE)   # SizeOfImage
open(DST, 'wb').write(data)

with open(LST, 'w') as f:
    f.write('PATCHED SITES (va, original bytes -> new bytes, purpose)\n')
    for va, o, n, desc in records:
        f.write('%#x  %s -> %s  %s\n' % (va, o.hex(), n.hex(), desc))
    f.write('\nNEW SECTION .kyty2p  RVA %#x  VA %#x  raw %#x  size %#x  (RWX)\n' % (NEWSEC_RVA, CODE, NEWSEC_RAW, NEWSEC_SIZE))
    f.write('data: g2 ptr @%#x, p2 device id @%#x, p2 bound @%#x, name @%#x\n' % (S['D_G2'], S['D_P2ID'], S['D_P2CL'], S['D_NAME']))
    f.write('header: NumberOfSections %d -> %d, SizeOfImage %#x -> %#x\n\n' % (nsec, nsec + 1, 0x3bcc000, NEWSEC_RVA + NEWSEC_SIZE))
    for a, enc, ln in code_listing:
        f.write(('%x: %-24s %s\n' % (a, enc.hex(), ln)) if a else ln + '\n')
print('ok: %d patches, %d bytes new code -> %s' % (len(records), len(code), DST))
