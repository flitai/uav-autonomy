/** A display cursor over already received backend time, never an authoritative clock. */
export class BufferedPlayback {
  value: bigint | null = null;
  private latest: bigint | null = null;
  private arrival = 0; private frame = 0; private fraction = 0;
  private rate = 0; private active = false;
  constructor(readonly buffer: bigint) { if (buffer <= 0n || buffer > 10000n) throw new Error('插值缓冲配置无效'); }
  reset(): void { this.value=null; this.latest=null; this.active=false; this.fraction=0; }
  observe(time: bigint, running: boolean, rate: number, wall: number): void {
    const active=running && Number.isFinite(rate) && rate>0 && rate<=1000;
    if (this.latest===null || time!==this.latest || active!==this.active || rate!==this.rate) this.arrival=wall;
    if (this.value===null) { this.value=time-this.buffer; this.frame=wall; }
    if (!active || !this.active) this.frame=wall;
    this.latest=time;this.active=active;this.rate=rate;
  }
  advance(wall: number): bigint | null {
    const elapsed=Math.max(0,Math.min(100,wall-this.frame));this.frame=wall;
    if (!this.active || this.value===null || this.latest===null) return this.value;
    // Monotonic local time paces known samples only. Slowly absorb arrival jitter rather than jumping on each packet.
    const sinceArrival=Math.max(0,Math.min(10000,wall-this.arrival));
    const target=this.latest-this.buffer+BigInt(Math.floor(sinceArrival*this.rate));
    const error=target-this.value;
    const correction=Math.max(-.1,Math.min(.1,Number(error>1000n?1000n:error< -1000n?-1000n:error)/10000));
    const step=elapsed*this.rate*(1+correction)+this.fraction;
    const whole=Math.floor(step);this.fraction=step-whole;
    const next=this.value+BigInt(whole);
    this.value=next<this.latest?next:this.latest;
    if (this.value===this.latest) this.fraction=0;
    return this.value;
  }
}
