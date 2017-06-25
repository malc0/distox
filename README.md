# distox
Scripts to interact with the DistoX surveying tools for the Androidphobic

Python 3 required.

*distox.py* lets you:

1. enter/exit CAL mode,
2. download the current set of calibration coefficients,
3. dump a load of measurements which (when mildly munged) can be ingested by tlx_calib, and
4. bung the output file of tlx_calib onto the device.

Both the original DistoX (based on the Leica DISTO A3) and the DistoX2 (Leica DISTO X310) are supported.

*distocsv2calib.py* lets you munge distox.py CSV output into tlx_calib input.

*calib_workflow* describes a suggested calibration workflow.

distox.py's Bluetooth discovery phase can be skipped by specifying a device address as an environment variable, e.g. `$ DX_ADDR=00:13:43:0C:7A:88 python3 distox.py toggleCAL`

tlx_calib comes from the topolinux project, available from https://code.google.com/archive/p/topolinux/
    
Technical information sourced from topolinux, http://paperless.bheeb.ch/download/DistoXAdvancedInformation.pdf and Beat Heeb's most helpful emails.
