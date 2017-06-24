#!/usr/bin/env python3

import bluetooth as bt
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

def df_append(df, d):
	hot = 1 * bool(d[0] & 0x80)
	typ = d[0] & 0x3f
	if typ == 0:
		pass
	elif typ == 1:
		dist = (int.from_bytes(d[1:3], 'little') + 65536 * bool(d[0] & 0x40)) / 1000
		heading = int.from_bytes(d[3:5], 'little') / 65536 * 360
		clino = int.from_bytes(d[5:7], 'little', signed = True) / 65536 * 360
		roll = d[7] / 256 * 360
		df.write('{},LEG,{},{},{},{}\n'.format(hot, dist, heading, clino, roll))
	elif typ == 2:
		Gx = int.from_bytes(d[1:3], 'little', signed = True)
		Gy = int.from_bytes(d[3:5], 'little', signed = True)
		Gz = int.from_bytes(d[5:7], 'little', signed = True)
		df.write('{},ACC,,,,,{},{},{}\n'.format(hot, Gx, Gy, Gz))
	elif typ == 3:
		Mx = int.from_bytes(d[1:3], 'little', signed = True)
		My = int.from_bytes(d[3:5], 'little', signed = True)
		Mz = int.from_bytes(d[5:7], 'little', signed = True)
		df.write('{},MAG,,,,,{},{},{}\n'.format(hot, Mx, My, Mz))
	else:
		raise RuntimeError('Unknown packet type', typ)

print('Discovering devices...')

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
		for a in range(0x8010, 0x8040, 4):	# FIXME: nonlin coeffs...
			cf.write(mem_read(s, a))
	print('... done.')
elif sys.argv[1] == 'loadcal':
	if len(sys.argv) < 3:
		raise RuntimeError('Specify input filename after \'loadcal\'')

	print('Writing device calibration from \'' + sys.argv[2] + '\'...')
	with open(sys.argv[2], 'rb') as cf:
		cal = cf.read()
	
	if cal[0:2] == b'0x':	# output from tlx_calib
		cal = bytes([int(i, 16) for i in str(cal[0:244], 'utf-8').split()])

	for o in range(0, 0x30, 4):	# FIXME: nonlin coeffs...
		mem_write(s, 0x8010 + o, cal[o:o + 4])
	print('... done.')
elif sys.argv[1] == 'dumpdata':
	if len(sys.argv) < 4:
		raise RuntimeError('Specify how many records (note one calibration measurement is *two* records), or \'all\'; and output CSV filename; after \'dumpdata\'')

	to_read = 4096 if sys.argv[2] == 'all' else int(sys.argv[2])
	dev_write_ptr = int.from_bytes(mem_read(s, 0xc020)[0:2], 'little')	# FIXME: this doesn't work on X310

	progress = 0
	print('Dumping ' + sys.argv[2] + ' measurements to \'' + sys.argv[3] + ('\' (don\'t let disto go to sleep!)...' if to_read > 150 else '\'...'))
	with open(sys.argv[3], 'w') as df:
		df.write('unread,type,dist,heading,clino,roll,x,y,z\n')

		read_ptr = dev_write_ptr - 8 * to_read
		if read_ptr < 0:
			addrs = list(range(read_ptr + 0x8000, 0x8000, 8)) + list(range(0, dev_write_ptr, 8))
		else:
			addrs = list(range(read_ptr, dev_write_ptr, 8))

		for a in addrs:
			data = mem_read(s, a)
			if data[0] != 0 and data[0] != 0xff:
				data += mem_read(s, a + 4)
				df_append(df, data)
			progress += 1
			if not progress % 128:
				print(str(progress * 100 / to_read) + '%')
	print('... done.')

# vim: ts=8 sts=8 sw=8 noexpandtab
