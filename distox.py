#!/usr/bin/env python3

import bluetooth as bt
import os
import sys
import time

class CommError(Exception):
	pass

def _mem_read(s, addr):
	req = bytes([0x38]) + addr.to_bytes(2, 'little')
	if s.send(req) != 3:
		raise CommError('Tx')
	rep = s.recv(8)
	if len(rep) != 8 or rep[0:3] != req:
		raise CommError('Rx')
	return rep[3:7]

def _mem_write(s, addr, data):
	req = bytes([0x39]) + addr.to_bytes(2, 'little') + data
	if s.send(req) != 7:
		raise CommError('Tx')
	rep = s.recv(8)
	if len(rep) != 8 or rep[0] != 0x38 or rep[1:7] != req[1:]:
		raise CommError('Rx')

def mem_read(s, addr):
	for _ in range(5):	# retries...
		try:
			return _mem_read(s, addr)
		except CommError as e:
			etype = e
	raise CommError('Memory read of 0x{:x} failed during '.format(addr) + etype.args[0])

def mem_write(s, addr, data):
	for _ in range(5):	# retries...
		try:
			return _mem_write(s, addr, data)
		except CommError as e:
			etype = e
	raise CommError('Memory write of 0x{:x} failed during '.format(addr) + etype.args[0])

def read_cal_mode(s, model):
	if model == 1:
		return bool(mem_read(s, 0x8000)[0] & 8)
	return bool(mem_read(s, 0xc044)[0] & 32)

def send_command(s, data):
	if s.send(bytes([data])) != 1:
		raise CommError('Send command of 0x{:x} failed'.format(data))

def segment_to_addr(i, model):
	if model == 1:
		return i * 8
	return int(i / 56) * 1024 + i % 56 * 18

def df_append(df, d, hot, ls_roll):
	hot *= 1
	typ = d[0] & 0x3f
	if typ == 0:
		pass
	elif typ == 1:
		dist = (int.from_bytes(d[1:3], 'little') + 65536 * bool(d[0] & 0x40)) / 1000
		if dist > 100000:
			dist = dist * 10 - 900000
		heading = int.from_bytes(d[3:5], 'little') / 65536 * 360
		clino = int.from_bytes(d[5:7], 'little', signed = True) / 65536 * 360
		roll = int.from_bytes((d[7], ls_roll), 'big', signed = True) / 65536 * 360
		df.write('{},LEG,{},{},{},{}\n'.format(hot, dist, heading, clino, roll))
	elif typ == 2:
		Gx = int.from_bytes(d[1:3], 'little', signed = True)
		Gy = int.from_bytes(d[3:5], 'little', signed = True)
		Gz = int.from_bytes(d[5:7], 'little', signed = True)
		cal_idx = d[7]
		df.write('{},ACC,,,,,{},{},{},{}\n'.format(hot, Gx, Gy, Gz, cal_idx))
	elif typ == 3:
		Mx = int.from_bytes(d[1:3], 'little', signed = True)
		My = int.from_bytes(d[3:5], 'little', signed = True)
		Mz = int.from_bytes(d[5:7], 'little', signed = True)
		cal_idx = d[7]
		df.write('{},MAG,,,,,{},{},{},{}\n'.format(hot, Mx, My, Mz, cal_idx))
	elif typ == 4:
		rev = 1 * bool(d[0] & 0x40)
		absG = int.from_bytes(d[1:3], 'little')
		absM = int.from_bytes(d[3:5], 'little')
		dip = int.from_bytes(d[5:7], 'little', signed = True)
		df.write('{},VEC,,,,,,,,,{},{},{},{}\n'.format(hot, rev, absG, absM, dip))
	else:
		raise RuntimeError('Unknown packet type', typ)

if 'DX_ADDR' in os.environ:
	addr = os.environ['DX_ADDR']
	name = bt.lookup_name(addr)
	if not name:
		raise RuntimeError('No DistoX found at ' + addr + ' (specified in DX_ADDR environment variable).')
	devs = [(addr, name)]
else:
	print('Discovering devices... (discovery can be skipped by setting the DX_ADDR environment variable)')

	devs = bt.discover_devices(lookup_names = True)

useaddr = ''
for addr, name in devs:
	if name == 'DistoX':
		model = 1	# DistoX (Leica DISTO A3)
	elif name.startswith('DistoX-'):
		model = 2	# DistoX2 (Leica DISTO X310)
	else:
		continue
	print('Found ' + addr + '.')
	if not useaddr:
		useaddr = addr
		usemodel = model
if useaddr:
	print('\nUsing ' + useaddr + '...')
	addr = useaddr
	model = usemodel
else:
	raise RuntimeError('No DistoX found.')

svcs = bt.find_service(name = 'COM1' if model == 1 else 'Serial', address = addr)

if not svcs:
	raise RuntimeError('Expected serial service not found on DistoX!?')

s = bt.BluetoothSocket(bt.RFCOMM)
s.connect((addr, svcs[0]['port']))

print('... connected.\n')

fwv = mem_read(s, 0xe000)
fw_ver = fwv[0] * 1000 + fwv[1]

print('Firmware version ' + str(int(fw_ver / 1000)) + '.' + str(fw_ver % 1000) + '.\n')

if len(sys.argv) < 2:
	raise RuntimeError('No action (toggleCAL/dumpcal/loadcal/dumpdata) specified, disconnecting.')

if sys.argv[1] == 'toggleCAL':
	cal_mode = read_cal_mode(s, model)
	print('CAL mode originally ' + ('on...' if cal_mode else 'off...'))

	send_command(s, 0x31 - cal_mode)
	time.sleep(.5)	# .1 is too short!

	print('CAL mode now ' + ('on.' if read_cal_mode(s, model) else 'off.'))
elif sys.argv[1] == 'dumpcal':
	if len(sys.argv) < 3:
		raise RuntimeError('Specify output filename after \'dumpcal\'')

	print('Saving device calibration to \'' + sys.argv[2] + '\'...')
	with open(sys.argv[2], 'wb') as cf:
		for a in range(0x8010, 0x8044, 4):
			cf.write(mem_read(s, a))
	print('... done.')
elif sys.argv[1] == 'loadcal':
	if len(sys.argv) < 3:
		raise RuntimeError('Specify input filename after \'loadcal\'')

	print('Writing device calibration from \'' + sys.argv[2] + '\'...')
	with open(sys.argv[2], 'rb') as cf:
		cal = cf.read()
	
	if cal[0:2] == b'0x':	# output from tlx_calib
		if cal[246:248] == b'0x':	# tlx_calib-alike, but with non-linear coefficients...
			cal = bytes([int(i, 16) for i in str(cal[0:260], 'utf-8').split()])
		else:
			cal = bytes([int(i, 16) for i in str(cal[0:244], 'utf-8').split()])

	cal = cal + b'\xff' * (-len(cal) % 4)	# pad with 0xff to 32 bit alignment
	if len(cal) > 48:	# non-linear case
		cal = cal[:52]	# guard against mad input
		if cal[48:] == b'\xff\xff\xff\xff':	# actually, linear variant
			cal = cal[:48]	# save flash wear
		elif model == 1 or fw_ver < 2003:
			raise RuntimeError('Writing extended (non-linear) calibration to this DistoX will not work (firmware too old): calibration unchanged')
	for o in range(0, len(cal), 4):
		mem_write(s, 0x8010 + o, cal[o:o + 4])
	print('... done.')
elif sys.argv[1] == 'dumpdata':
	if len(sys.argv) < 4:
		raise RuntimeError('Specify how many records' + (' (note one calibration measurement is *two* records)' if model == 1 else '') + ', or \'all\'; and output CSV filename; after \'dumpdata\'')

	if model == 1:
		max_segments = 4096
		dev_write_idx = int.from_bytes(mem_read(s, 0xc020)[0:2], 'little') / 8
	else:
		max_segments = 1064
		dev_write_idx = int.from_bytes(mem_read(s, 0xe008)[0:2], 'little')
	to_read = max_segments if sys.argv[2] == 'all' else int(sys.argv[2])

	progress = 0
	print('Dumping ' + sys.argv[2] + ' measurements to \'' + sys.argv[3] + ('\' (don\'t let disto go to sleep!)...' if to_read > 150 and model == 1 else '\'...'))
	with open(sys.argv[3], 'w') as df:
		df.write('unread,type,dist,heading,clino,roll,x,y,z,cal_idx,rev,ACC,MAG,dip\n')

		read_idx = dev_write_idx - to_read
		if read_idx < 0:
			addrs = [ segment_to_addr(i, model) for i in list(range(read_idx + max_segments, max_segments)) + list(range(dev_write_idx)) ]
		else:
			addrs = [ segment_to_addr(i, model) for i in range(read_idx, dev_write_idx) ]

		for a in addrs:
			data = mem_read(s, a)
			if data[0] != 0 and data[0] != 0xff:
				data += mem_read(s, a + 4)
				if model == 1:
					df_append(df, data, bool(data[0] & 0x80), 0)
				else:
					data += mem_read(s, a + 8)
					data += mem_read(s, a + 12)
					data += mem_read(s, a + 16)
					df_append(df, data, data[16] & 1, data[15])
					df_append(df, data[8:16], data[17] & 1, 0)
			progress += 1
			if not progress % 128:
				print(str(progress * 100 / to_read) + '%')
	print('... done.')

# vim: ts=8 sts=8 sw=8 noexpandtab
