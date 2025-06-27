# =============================================================================
# Title: TouchDesigner ↔︎ Wekinator OSC Bridge
# Author: M. Saim Gülay
# Contact: github.com/saimgulay
# Version: 1.0.0
# Date: 2025-06-27
# License: MIT License
#
# Description:
# A fully scriptable and fault-tolerant Script CHOP that provides complete
# OSC-based control over Wekinator's training, inference, and example
# management pipeline from within TouchDesigner.
#
# This tool is designed for use in HCI prototyping, real-time performance
# systems, and interactive machine learning applications where precise and
# autonomous integration with Wekinator is required.
#
# Dependencies:
# - None external (standard Python + TouchDesigner context)
# =============================================================================


import td
import socket
import struct
import threading
import collections

# --- OSC SENDING FUNCTION (EXAMPLE METHOD) ---
def send_osc_message(host, port, address, *args):
    # prepare address and pad
    msg = address.encode('utf-8') + b'\0'
    msg += (b'\0' * ((4 - len(msg) % 4) % 4))
    # typetags and data
    typetags = ','
    data_bytes = b''
    for arg in args:
        if isinstance(arg, float):
            typetags += 'f'
            data_bytes += struct.pack('>f', arg)
        elif isinstance(arg, int):
            typetags += 'i'
            data_bytes += struct.pack('>i', arg)
        elif isinstance(arg, str):
            typetags += 's'
            data_bytes += arg.encode('utf-8') + b'\0'
            data_bytes += (b'\0' * ((4 - len(arg) % 4) % 4))
    # pad typetag
    msg += typetags.encode('utf-8') + b'\0'
    msg += (b'\0' * ((4 - len(msg) % 4) % 4))
    msg += data_bytes
    # send
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(msg, (host, port))
        # debug prints commented out for performance
    except Exception:
        pass

# --- Safely reset any previous socket/thread ---
try:
    old_socket = globals().get('sock_in')
    if old_socket:
        old_socket.close()
except:
    pass
try:
    if hasattr(init_sockets, '_thread_started'):
        init_sockets._thread_started = False
except:
    pass

# --- OSC packing/unpacking utilities ---
def pad4(data: bytes) -> bytes:
    return data + (b"\0" * ((4 - len(data) % 4) % 4))

def build_osc(address: str, *args) -> bytes:
    msg = pad4(address.encode('utf-8'))
    typetags = ','
    data_bytes = b''
    for arg in args:
        if isinstance(arg, float):
            typetags += 'f'; data_bytes += struct.pack('>f', arg)
        elif isinstance(arg, int):
            typetags += 'i'; data_bytes += struct.pack('>i', arg)
        elif isinstance(arg, str):
            typetags += 's'; data_bytes += pad4(arg.encode('utf-8'))
    msg += pad4(typetags.encode('utf-8'))
    msg += data_bytes
    return msg

def unpack_osc_packet(packet: bytes):
    try:
        e = packet.find(b'\0')
        if e < 0: return None, [], []
        addr = packet[:e].decode('utf-8')
        ts = ((e + 4)//4)*4
        te = packet.find(b'\0', ts)
        if te < 0: return addr, [], []
        tags = packet[ts:te].decode('utf-8')
        if not tags.startswith(','): return addr, [], []
        tags = tags[1:]
        ds = ((te + 4)//4)*4
        vals, off = [], ds
        for t in tags:
            if t == 'f':
                vals.append(struct.unpack('>f', packet[off:off+4])[0]); off += 4
            elif t == 'i':
                vals.append(struct.unpack('>i', packet[off:off+4])[0]); off += 4
            elif t == 's':
                se = packet.find(b'\0', off)
                vals.append(packet[off:se].decode('utf-8'))
                off = ((se + 4)//4)*4
        return addr, list(tags), vals
    except:
        return None, [], []

# --- Global state ---
sock_in             = None
wekinator_recording = False
wekinator_trained   = False
wekinator_running   = False
data_lock           = threading.Lock()
received_osc_data   = collections.defaultdict(list)
dtw_triggers        = {}

# --- Default OSC settings ---
TD_LISTEN_PORT        = 12000
WEKINATOR_HOST        = '127.0.0.1'
WEKINATOR_LISTEN_PORT = 6448
OSC_INPUT_MSG         = '/wek/inputs'
OSC_OUTPUT_MSG        = '/wek/outputs'

def recv_loop():
    while sock_in:
        try:
            pkt, _ = sock_in.recvfrom(4096)
            addr, tags, vals = unpack_osc_packet(pkt)
            if not addr: continue
            with data_lock:
                if addr.startswith('/output_'):
                    try:
                        idx = int(addr.rsplit('_',1)[1])
                        dtw_triggers[idx] = 1
                    except:
                        received_osc_data[addr] = vals
                else:
                    received_osc_data[addr] = vals
        except socket.error:
            break
        except:
            break

def init_sockets(op):
    global sock_in
    if sock_in:
        try: sock_in.close()
        except: pass
        sock_in = None
    try:
        port = op.par.Tdlistenport.eval()
        sock_in = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock_in.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock_in.bind(('0.0.0.0', port))
        sock_in.setblocking(True)
    except Exception as e:
        op.addError(f"Cannot bind listening port {port}: {e}")
        sock_in = None
        return
    init_sockets._thread = threading.Thread(target=recv_loop, daemon=True)
    init_sockets._thread.start()
    init_sockets._thread_started = True

def send_to_wekinator(op, address, *args):
    host = op.par.Wekinatorhost.eval()
    port = op.par.Wekinatorlistenport.eval()
    send_osc_message(host, port, address, *args)

def onSetupParameters(op):
    if op.customPages: return
    pg = op.appendCustomPage('General')
    sf = pg.appendFloat('Samplerate', label='Sample Rate')[0]; sf.normMin, sf.normMax, sf.val = 30, 120, 60
    ni = pg.appendInt('Numinputs', label='Number of Inputs')[0]; ni.normMin, ni.normMax, ni.val = 1, 128, 2

    pg = op.appendCustomPage('OSC')
    tdport = pg.appendInt('Tdlistenport', label='TD Listening Port')[0]; tdport.val = TD_LISTEN_PORT
    whost  = pg.appendStr('Wekinatorhost', label='Wekinator Host')[0]; whost.val = WEKINATOR_HOST
    wport  = pg.appendInt('Wekinatorlistenport', label='Wekinator Port')[0]; wport.val = WEKINATOR_LISTEN_PORT
    # 'Send Test' feature removed
    inmsg = pg.appendStr('Inputmessage', label='Input OSC Address')[0]; inmsg.val = OSC_INPUT_MSG
    outmsg = pg.appendStr('Outputmessage', label='Main Output OSC Address')[0]; outmsg.val = OSC_OUTPUT_MSG

    pg = op.appendCustomPage('Input Sending')
    m = pg.appendMenu('Sendingmode', label='Mode')[0]
    m.menuNames, m.menuLabels = ['Automatic', 'Manual'], ['Every Frame', 'On Pulse']
    pg.appendPulse('Sendnow', label='Send Input Now')

    pg = op.appendCustomPage('Control')
    pg.appendToggle('Record', label='Record Examples')
    pg.appendToggle('Train',  label='Train Model')
    pg.appendToggle('Run',    label='Run Models')
    pg.appendPulse('Canceltrain', label='Cancel Training')

    pg = op.appendCustomPage('DTW Control')
    gid = pg.appendInt('Gestureid', label='Gesture ID')[0]; gid.normMin, gid.normMax, gid.val = 1,16,1
    pg.appendPulse('Startdtwrecording', label='Start DTW Recording')
    pg.appendPulse('Stopdtwrecording',  label='Stop DTW Recording')

    pg = op.appendCustomPage('Example Management')
    pg.appendPulse('Deleteallexamples',    label='Delete All Examples')
    to = pg.appendInt('Targetoutput',       label='Target Output')[0]; to.normMin, to.normMax, to.val = 1,16,1
    pg.appendPulse('Deleteoutputexamples',  label='Delete Examples for Output')
    sv = pg.appendStr('Setoutputvalues',    label='Output Values (CSV)')[0]; sv.val = ''
    pg.appendPulse('Sendoutputvalues',      label='Send Output Values')

    pg = op.appendCustomPage('Advanced')
    nl = pg.appendStr('Namelist', label='Names (CSV)')[0]; nl.val = ''
    pg.appendPulse('Setinputnames',  label='Set Input Names')
    pg.appendPulse('Setoutputnames', label='Set Output Names')
    ml = pg.appendStr('Modellist', label='Model Indices (CSV)')[0]; ml.val = ''
    pg.appendPulse('Enablemodelrecording',  label='Enable Model Recording')
    pg.appendPulse('Disablemodelrecording', label='Disable Model Recording')
    pg.appendPulse('Enablemodelrunning',    label='Enable Model Running')
    pg.appendPulse('Disablemodelrunning',   label='Disable Model Running')

pulse_map = {
    'Canceltrain':          '/wekinator/control/cancelTrain',
    'Deleteallexamples':    '/wekinator/control/deleteAllExamples',
    'Deleteoutputexamples': '/wekinator/control/deleteExamplesForOutput',
    'Startdtwrecording':    '/wekinator/control/startDtwRecording',
    'Stopdtwrecording':     '/wekinator/control/stopDtwRecording',
    'Sendoutputvalues':     '/wekinator/control/outputs',
    'Setinputnames':        '/wekinator/control/setInputNames',
    'Setoutputnames':       '/wekinator/control/setOutputNames',
    'Enablemodelrecording': '/wekinator/control/enableModelRecording',
    'Disablemodelrecording':'/wekinator/control/disableModelRecording',
    'Enablemodelrunning':   '/wekinator/control/enableModelRunning',
    'Disablemodelrunning':  '/wekinator/control/disableModelRunning',
}

def onPulse(par):
    op = par.owner
    if par.name == 'Sendnow':
        if op.inputs:
            vals = [c[0] for c in op.inputs[0].chans()[:op.par.Numinputs.eval()]]
            send_to_wekinator(op, op.par.Inputmessage.eval(), *vals)
        return
    if par.name in pulse_map:
        cmd = pulse_map[par.name]; args = []
        if par.name == 'Startdtwrecording':
            args = [op.par.Gestureid.eval()]
        elif par.name == 'Deleteoutputexamples':
            args = [op.par.Targetoutput.eval()]
        elif par.name == 'Sendoutputvalues':
            try: args = [float(v) for v in op.par.Setoutputvalues.eval().split(',') if v.strip()]
            except: pass
        elif par.name in ('Setinputnames','Setoutputnames'):
            args = [s.strip() for s in op.par.Namelist.eval().split(',') if s.strip()]
        elif par.name in ('Enablemodelrecording','Disablemodelrecording','Enablemodelrunning','Disablemodelrunning'):
            try: args = [int(i) for i in op.par.Modellist.eval().split(',') if i.strip()]
            except: pass
        send_to_wekinator(op, cmd, *args)

def onCook(op):
    if not op.customPages: onSetupParameters(op)
    if sock_in is None or not getattr(init_sockets,'_thread_started',False):
        init_sockets(op)
    op.isTimeSlice = False; op.clear()

    # poll toggles
    rec = bool(op.par.Record.eval())
    if rec != wekinator_recording:
        globals()['wekinator_recording'] = rec
        send_to_wekinator(op, '/wekinator/control/startRecording' if rec else '/wekinator/control/stopRecording')

    trn = bool(op.par.Train.eval())
    if trn != wekinator_trained:
        globals()['wekinator_trained'] = trn
        send_to_wekinator(op, '/wekinator/control/train' if trn else '/wekinator/control/cancelTrain')

    run = bool(op.par.Run.eval())
    if run != wekinator_running:
        globals()['wekinator_running'] = run
        send_to_wekinator(op, '/wekinator/control/startRunning' if run else '/wekinator/control/stopRunning')

    # automatic sending
    if op.par.Sendingmode.menuIndex == 0 and op.inputs:
        vals = [c[0] for c in op.inputs[0].chans()[:op.par.Numinputs.eval()]]
        send_to_wekinator(op, op.par.Inputmessage.eval(), *vals)

    # build output channels
    with data_lock:
        main = op.par.Outputmessage.eval()
        outs = received_osc_data.get(main, [])
        for i,v in enumerate(outs):
            op.appendChan(f'output{i+1}').vals=[v]
        for addr,vals in received_osc_data.items():
            if addr == main: continue
            base = addr.replace('/','_').strip('_')
            for i,v in enumerate(vals):
                op.appendChan(f'{base}{i+1}').vals=[v]
        for gid,tr in dtw_triggers.items():
            op.appendChan(f'dtw_event_{gid}').vals=[tr]
        dtw_triggers.clear()

    op.numSamples = 1
    op.rate       = op.par.Samplerate.eval()

def onExit():
    global sock_in
    if sock_in:
        try: sock_in.close()
        except: pass
        sock_in = None
    if hasattr(init_sockets,'_thread_started'):
        init_sockets._thread_started = False
