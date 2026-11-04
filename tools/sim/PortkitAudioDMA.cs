//
// STM32H7 DMA (DMA1/DMA2 register layout) for the Bitbox micro simulation, replacing Renode's STM32DMA on DMA2.
// Renode's model has no circular mode and no half-transfer interrupt; the micro's audio runs on two circular streams
// (DMA2 stream 1: RAM -> SAI1 A, stream 5: SAI1 B -> RAM), and audioTask (with the engine, and the button polling in
// it) waits for their half / complete interrupts. Here an audio clock ticks at tickHz (default 375 Hz = 128 frames at
// 48 kHz, one engine block per buffer half): every enabled circular stream alternately raises HTIF and TCIF.
// Audio: CaptureTo(stream, path) appends, at every tick, the buffer half the firmware has just finished (raw 32-bit
// words, the SAI's TDM frames: 8 slots); InputFrom(stream, path) writes the half the firmware reads next from a raw
// file of the same format (looped; zeros when not set). Non-circular transfers memory -> peripheral
// / memory -> memory are done at once on enable (like Renode's model); peripheral -> memory completes at once.
//
// Loaded at run time: include @sim/PortkitAudioDMA.cs (see sim/boot.resc).
//
using System;
using System.Collections.Generic;
using System.IO;

using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.DMA
{
    public class PortkitAudioDMA : IDoubleWordPeripheral, IKnownSize, INumberedGPIOOutput, IGPIOReceiver
    {
        public PortkitAudioDMA(IMachine machine, long tickHz = 375)
        {
            sysbus = machine.GetSystemBus(this);
            var connections = new Dictionary<int, IGPIO>();
            for(var i = 0; i < Streams; i++)
            {
                irqs[i] = new GPIO();
                connections[i] = irqs[i];
            }
            Connections = connections;
            timer = new LimitTimer(machine.ClockSource, 1000000, this, "audioClock", (ulong)(1000000 / tickHz),
                Direction.Descending, enabled: true, workMode: WorkMode.Periodic, eventEnabled: true, autoUpdate: true);
            timer.LimitReached += Tick;
            Reset();
        }

        public long Size => 0x400;

        public IReadOnlyDictionary<int, IGPIO> Connections { get; }

        public ulong Ticks { get; private set; }

        public void CaptureTo(int stream, string path)
        {
            captureStream = stream;
            capture = new FileStream(path, FileMode.Create, FileAccess.Write);
        }

        public void CaptureStop()
        {
            capture?.Flush();
            capture?.Dispose();
            capture = null;
        }

        public void InputFrom(int stream, string path)
        {
            inputStream = stream;
            input = File.ReadAllBytes(path);
            inputPos = 0;
        }

        public void Reset()
        {
            Array.Clear(cr, 0, Streams);
            Array.Clear(ndtr, 0, Streams);
            Array.Clear(ndtrStart, 0, Streams);
            Array.Clear(par, 0, Streams);
            Array.Clear(m0ar, 0, Streams);
            Array.Clear(m1ar, 0, Streams);
            Array.Clear(fcr, 0, Streams);
            Array.Clear(flags, 0, Streams);
            Array.Clear(half, 0, Streams);
            Ticks = 0;
            UpdateInterrupts();
        }

        public void OnGPIO(int number, bool value)
        {
            // peripheral requests (DMAMUX) are not needed: circular streams run on the audio clock
        }

        public uint ReadDoubleWord(long offset)
        {
            if(offset == 0x00 || offset == 0x04)          // LISR / HISR
            {
                var first = offset == 0x00 ? 0 : 4;
                uint v = 0;
                for(var k = 0; k < 4; k++)
                {
                    v |= (uint)flags[first + k] << Shift[k];
                }
                return v;
            }
            if(offset == 0x08 || offset == 0x0C)
            {
                return 0;
            }
            var s = StreamOf(offset, out var reg);
            if(s < 0)
            {
                return 0;
            }
            switch(reg)
            {
                case 0x00: return cr[s];
                case 0x04: return ndtr[s];
                case 0x08: return par[s];
                case 0x0C: return m0ar[s];
                case 0x10: return m1ar[s];
                case 0x14: return fcr[s] | 0x20;                // FS: FIFO empty
            }
            return 0;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset == 0x08 || offset == 0x0C)          // LIFCR / HIFCR: write 1 to clear
            {
                var first = offset == 0x08 ? 0 : 4;
                for(var k = 0; k < 4; k++)
                {
                    flags[first + k] &= (byte)~((value >> Shift[k]) & 0x3D);
                }
                UpdateInterrupts();
                return;
            }
            var s = StreamOf(offset, out var reg);
            if(s < 0)
            {
                return;
            }
            switch(reg)
            {
                case 0x00:
                    var wasEnabled = (cr[s] & EN) != 0;
                    cr[s] = value;
                    if(!wasEnabled && (value & EN) != 0)
                    {
                        Start(s);
                    }
                    UpdateInterrupts();
                    break;
                case 0x04: ndtr[s] = value & 0xFFFF; break;
                case 0x08: par[s] = value; break;
                case 0x0C: m0ar[s] = value; break;
                case 0x10: m1ar[s] = value; break;
                case 0x14: fcr[s] = value; break;
            }
        }

        private void Start(int s)
        {
            ndtrStart[s] = ndtr[s];
            half[s] = 0;
            if((cr[s] & CIRC) != 0)
            {
                return;                                  // runs on the audio clock
            }
            var dir = (cr[s] >> 6) & 3;
            var msize = 1 << (int)((cr[s] >> 13) & 3);
            var psize = 1 << (int)((cr[s] >> 11) & 3);
            if(dir == 1 || dir == 2)                     // memory -> peripheral / memory -> memory: copy at once
            {
                var n = (int)ndtr[s];
                for(var i = 0; i < n; i++)
                {
                    var src = dir == 2 ? par[s] + ((cr[s] & PINC) != 0 ? (ulong)(i * psize) : 0)
                                       : m0ar[s] + ((cr[s] & MINC) != 0 ? (ulong)(i * msize) : 0);
                    var dst = dir == 2 ? m0ar[s] + ((cr[s] & MINC) != 0 ? (ulong)(i * msize) : 0)
                                       : par[s] + ((cr[s] & PINC) != 0 ? (ulong)(i * psize) : 0);
                    var size = dir == 2 ? psize : msize;
                    if(size == 4)
                    {
                        sysbus.WriteDoubleWord(dst, sysbus.ReadDoubleWord(src));
                    }
                    else if(size == 2)
                    {
                        sysbus.WriteWord(dst, sysbus.ReadWord(src));
                    }
                    else
                    {
                        sysbus.WriteByte(dst, sysbus.ReadByte(src));
                    }
                }
            }
            ndtr[s] = 0;
            cr[s] &= ~EN;
            flags[s] |= TCIF;
        }

        private void Tick()
        {
            Ticks++;
            var any = false;
            for(var s = 0; s < Streams; s++)
            {
                if((cr[s] & (EN | CIRC)) != (EN | CIRC))
                {
                    continue;
                }
                var bytes = (int)(ndtrStart[s] / 2) * (1 << (int)((cr[s] >> 13) & 3));    // one half, in memory units
                var nextHalf = m0ar[s] + (ulong)(half[s] == 0 ? 0 : bytes);              // the firmware's next half
                var doneHalf = m0ar[s] + (ulong)(half[s] == 0 ? bytes : 0);              // the one it has just filled
                if(capture != null && s == captureStream && Ticks > 2)
                {
                    capture.Write(sysbus.ReadBytes(doneHalf, bytes), 0, bytes);
                }
                if(input != null && s == inputStream && input.Length >= bytes)
                {
                    var chunk = new byte[bytes];
                    for(var k = 0; k < bytes; k++)
                    {
                        chunk[k] = input[inputPos];
                        inputPos = (inputPos + 1) % input.Length;
                    }
                    sysbus.WriteBytes(chunk, nextHalf);
                }
                if(half[s] == 0)
                {
                    flags[s] |= HTIF;
                    ndtr[s] = ndtrStart[s] / 2;
                }
                else
                {
                    flags[s] |= TCIF;
                    ndtr[s] = ndtrStart[s];
                }
                half[s] ^= 1;
                any = true;
            }
            if(any)
            {
                UpdateInterrupts();
            }
        }

        private void UpdateInterrupts()
        {
            for(var s = 0; s < Streams; s++)
            {
                var on = ((flags[s] & HTIF) != 0 && (cr[s] & HTIE) != 0)
                      || ((flags[s] & TCIF) != 0 && (cr[s] & TCIE) != 0);
                irqs[s].Set(on);
            }
        }

        private static int StreamOf(long offset, out long reg)
        {
            reg = 0;
            if(offset < 0x10 || offset >= 0x10 + Streams * 0x18)
            {
                return -1;
            }
            reg = (offset - 0x10) % 0x18;
            return (int)((offset - 0x10) / 0x18);
        }

        private const int Streams = 8;
        private const uint EN = 1u << 0, HTIE = 1u << 3, TCIE = 1u << 4, CIRC = 1u << 8, PINC = 1u << 9, MINC = 1u << 10;
        private const byte HTIF = 1 << 4, TCIF = 1 << 5;
        private static readonly int[] Shift = { 0, 6, 16, 22 };

        private FileStream capture;
        private int captureStream = -1;
        private byte[] input;
        private int inputStream = -1, inputPos;

        private readonly IBusController sysbus;
        private readonly LimitTimer timer;
        private readonly GPIO[] irqs = new GPIO[Streams];
        private readonly uint[] cr = new uint[Streams], ndtr = new uint[Streams], ndtrStart = new uint[Streams];
        private readonly uint[] par = new uint[Streams], m0ar = new uint[Streams], m1ar = new uint[Streams];
        private readonly uint[] fcr = new uint[Streams];
        private readonly byte[] flags = new byte[Streams];
        private readonly int[] half = new int[Streams];
    }
}
