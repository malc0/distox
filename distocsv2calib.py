#!/usr/bin/env python3

import csv
import sys

with open(sys.argv[1], 'r') as df:
	reader = csv.reader(df)
	acc = False
	for row in reader:
		# FIXME: cmdline df row slicing support
		if row[1] == 'ACC':
			acc = '{:x} {:x} {:x} '.format(int(row[6]), int(row[7]), int(row[8]))
		elif acc and row[1] == 'MAG':
			print(acc + '{:x} {:x} {:x} -1 0'.format(int(row[6]), int(row[7]), int(row[8])))

# vim: ts=8 sts=8 sw=8 noexpandtab
