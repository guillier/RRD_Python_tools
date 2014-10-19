#!/usr/bin/env python3
"""
Converter for RRD files between ARMv6l and x86_64 (AMD/Intel 64bit)
architectures. Other architectures are not supported.

The MIT License (MIT)

Copyright (c) 2014 François GUILLIER <dev @ guillier . org>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
    THE SOFTWARE.
"""

from struct import pack, unpack

## Info about file format comes from the RRD sources:
## https://github.com/oetiker/rrdtool-1.x/blob/master/src/rrd_format.h
## https://github.com/oetiker/rrdtool-1.x/blob/master/src/rrd_open.c

fs = None
fd = None

def long_read4_write8():
    """Read 4 bytes and write with 4 Nulls. Return the packed value"""
    pval = fs.read(4)
    fd.write(pval)
    fd.write(b'\x00\x00\x00\x00')
    return pval


def long_read8_write4():
    """Read and write 4 bytes and read and ignore 4 more.
       Return the packed value"""
    pval = fs.read(4)
    fd.write(pval)
    fs.read(4)
    return pval


def double_read_write_swap_nan():
    dbl = fs.read(8)
    if dbl == b'\x00\x00\x00\x00\x00\x00\xf8\x7f':
        dbl = b'\x00\x00\x00\x00\x00\x00\xf8\xff'
    elif dbl == b'\x00\x00\x00\x00\x00\x00\xf8\xff':
        dbl = b'\x00\x00\x00\x00\x00\x00\xf8\x7f'
    fd.write(dbl)
    return dbl


def read_header():
    arch_test = 0
    if fs.read(4) != b'RRD\x00':
        raise Exception("Format issue: COOKIE")
    if fs.read(5) != b'0003\x00':
        raise Exception("Format issue: VERSION")
    if fs.read(7) != b'\x00\x00\x00\x00\x00\x00\x00':
        raise Exception("Format issue: ARCHITECTURE")
    if unpack('d', fs.read(8))[0] != 8.642135e+130:
        raise Exception("Format issue: FLOAT COOKIE")
    ds_cnt = unpack('=L', fs.read(4))[0]
    if ds_cnt == 0:
        raise Exception("Format issue: DS COUNT")
    rra_cnt = unpack('=L', fs.read(4))[0]
    if rra_cnt == 0:
        arch_test += 1
        rra_cnt = unpack('=L', fs.read(4))[0]
    if rra_cnt == 0:
        raise Exception("Format issue: RRA COUNT")
    pdp_step = unpack('=L', fs.read(4))[0]
    if pdp_step == 0:
        arch_test += 1
        pdp_step = unpack('=L', fs.read(4))[0]
    fs.read(4); # Padding (x86_64) or structure alignment (armv6l)
    if pdp_step == 0:
        raise Exception("Format issue: PDP STEP")
    if arch_test != 0 and arch_test != 2:
        raise Exception("Format issue: ALIGNMENT")
    arch = 'x86_64' if arch_test == 2 else 'armv6l'
    fs.read(80);
    return (arch, ds_cnt, rra_cnt, pdp_step)


def write_header(arch, ds_cnt, rra_cnt, pdp_step):
    fd.write(b'RRD\x000003\x00\x00\x00\x00\x00\x00\x00\x00')
    fd.write(b'\x2f\x25\xc0\xc7\x43\x2b\x1f\x5b')
    fd.write(pack('=L', ds_cnt))
    if arch == 'x86_64':
        fd.write(b'\x00\x00\x00\x00')
    fd.write(pack('=L', rra_cnt))
    if arch == 'x86_64':
        fd.write(b'\x00\x00\x00\x00')
    fd.write(pack('=L', pdp_step))
    fd.write(b'\x00\x00\x00\x00')  # Padding (x86_64) or structure alignment (armv6l)
    fd.write(b'\x00' * 80)


def rrd_convert(src_filename, dst_filename, arch_dest):
    global fs, fd
    with open(src_filename, 'rb') as fs:
        (arch_src, ds_cnt, rra_cnt, pdp_step) = read_header()
        long_rw_func = None
        if arch_src == 'armv6l' and arch_dest == 'x86_64':
            long_rw_func = long_read4_write8
        if arch_src == 'x86_64' and arch_dest == 'armv6l':
            long_rw_func = long_read8_write4
        assert(long_rw_func)
        with open(dst_filename, 'wb') as fd:
            write_header(arch_dest, ds_cnt, rra_cnt, pdp_step)

            ### __rrd_read(rrd->ds_def, ds_def_t, rrd->stat_head->ds_cnt);
            for ds in range(0, ds_cnt):
                fd.write(fs.read(40))
                for i in range(0, 10):
                    double_read_write_swap_nan()

            row_cnt = 0
            ### __rrd_read(rrd->rra_def, rra_def_t, rrd->stat_head->rra_cnt);
            for rra in range(0, rra_cnt):
                fd.write(fs.read(20))
                if arch_dest == 'x86_64':
                    fd.write(b'\x00\x00\x00\x00')  # Padding
                if arch_src == 'x86_64':
                    fs.read(4)  # Padding
                row_cnt += unpack('=L', long_rw_func())[0]
                long_rw_func()
                if arch_src == 'armv6l':
                    fs.read(4)  # Padding
                if arch_dest == 'armv6l':
                    fd.write(b'\x00\x00\x00\x00')  # Padding
                for i in range(0, 10):
                    double_read_write_swap_nan()
            long_rw_func()
            long_rw_func()

            ### __rrd_read(rrd->pdp_prep, pdp_prep_t, rrd->stat_head->ds_cnt);
            fd.write(fs.read(112 * ds_cnt))

            ### __rrd_read(rrd->cdp_prep, cdp_prep_t, rrd->stat_head->rra_cnt * rrd->stat_head->ds_cnt);
            for i in range(0, 10 * ds_cnt * rra_cnt):
                double_read_write_swap_nan()

            ### __rrd_read(rrd->rra_ptr, rra_ptr_t, rrd->stat_head->rra_cnt);
            for rra in range(0, rra_cnt):
                long_rw_func()
            length_header_dst = fd.tell()

            ###  __rrd_read(rrd->rrd_value, rrd_value_t, row_cnt * rrd->stat_head->ds_cnt);
            for i in range(0, row_cnt * ds_cnt):
                double_read_write_swap_nan()

            assert(fd.tell() == length_header_dst + 8 * row_cnt * ds_cnt)

if __name__ == "__main__":
    rrd_convert('file_armv6l.rrd', 'file_x86_64.rrd', 'x86_64')
    rrd_convert('file_x86_64.rrd', 'file_armv6l__new.rrd', 'armv6l')
