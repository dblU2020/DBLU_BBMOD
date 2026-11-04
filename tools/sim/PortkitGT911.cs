//
// Goodix GT911 touch controller for the Bitbox micro simulation (I2C1, 7-bit address 0x5d; the firmware's driver is
// 0x08046154 (init: product id 0x8140, status 0x814e) and 0x08046548 (poll)).
// Register access: a write starts with the 16-bit register address (big endian), further bytes are stored; reads
// continue from the current address. The poll reads status 0x814e (bit 7 = ready, bits 0-2 = points), then 7 bytes
// per point from 0x814f + 8 n (track id, coordinate 1 lo / hi, coordinate 2 lo / hi, size lo / hi), then writes 0 to
// 0x814e. The firmware takes coordinate 2 (0..319) as the UI's x and coordinate 1 (0..239) as its y.
//
// Touch(x, y) / Release() from the monitor, in the firmware's UI coordinates (see sim/run.py "touch").
//
// Loaded at run time: include @sim/PortkitGT911.cs.
//
using System.Collections.Generic;

using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.I2C;

namespace Antmicro.Renode.Peripherals.Input
{
    public class PortkitGT911 : II2CPeripheral
    {
        public PortkitGT911()
        {
            Reset();
        }

        public void Reset()
        {
            regs.Clear();
            address = 0;
            touched = false;
            regs[0x8140] = (byte)'9';
            regs[0x8141] = (byte)'1';
            regs[0x8142] = (byte)'1';
        }

        public void Touch(int x, int y)
        {
            touched = true;
            tx = x;
            ty = y;
            Reads = 0;
        }

        public void Release()
        {
            touched = false;
        }

        public int Reads { get; private set; }

        public void Write(byte[] data)
        {
            if(data.Length < 2)
            {
                return;
            }
            address = (data[0] << 8) | data[1];
            for(var k = 2; k < data.Length; k++)
            {
                regs[address++] = data[k];
            }
        }

        public byte[] Read(int count = 1)
        {
            var result = new byte[count];
            for(var k = 0; k < count; k++, address++)
            {
                result[k] = Get(address);
            }
            return result;
        }

        public void FinishTransmission()
        {
        }

        private byte Get(int reg)
        {
            if(reg == 0x814E)
            {
                Reads++;
                return (byte)(0x80 | (touched ? 1 : 0));          // always a fresh frame: 1 point or none (release)
            }
            if(reg >= 0x814F && reg < 0x814F + 8)
            {
                switch(reg - 0x814F)
                {
                    case 0: return 0;                              // track id
                    case 1: return (byte)(ty & 0xFF);              // coordinate 1 -> UI y
                    case 2: return (byte)(ty >> 8);
                    case 3: return (byte)(tx & 0xFF);              // coordinate 2 -> UI x
                    case 4: return (byte)(tx >> 8);
                    case 5: return 0x20;                           // size
                    default: return 0;
                }
            }
            return regs.TryGetValue(reg, out var v) ? v : (byte)0;
        }

        private readonly Dictionary<int, byte> regs = new Dictionary<int, byte>();
        private int address;
        private bool touched;
        private int tx, ty;
    }
}
