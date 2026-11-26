import { memo, useState, useEffect, useRef } from 'react';
import { Mic } from 'lucide-react';

export default memo(function MicLevelMeter({ stream = null, isActive = false, className = '', barCount = 12, label = 'Microphone Level' }) {
  const [isSupported, setIsSupported] = useState(true);
  const barsRef = useRef(null);
  useEffect(() => {
    const bars = barsRef.current?.children || [];
    const paint = level => Array.from(bars).forEach((bar, index) => {
      bar.style.opacity = index < Math.round(level * barCount) ? '1' : '.2';
      bar.style.transform = index < Math.round(level * barCount) ? 'scaleY(1.1)' : 'scaleY(1)';
    });
    paint(0);
    if (!stream || !isActive) return;
    let context, source, analyser, frame, last = -Infinity, disposed = false;
    const close = () => {
      disposed = true;
      if (frame != null) cancelAnimationFrame(frame);
      source?.disconnect(); analyser?.disconnect();
      context?.close().catch(() => {});
    };
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      context = new AudioContext();
      analyser = context.createAnalyser(); analyser.fftSize = 256; analyser.smoothingTimeConstant = .5;
      source = context.createMediaStreamSource(stream); source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const update = now => {
        if (disposed) return;
        if (now - last >= 1000 / 15) {
          last = now; analyser.getByteFrequencyData(data);
          paint(Math.min(1, data.reduce((sum, value) => sum + value, 0) / data.length / 128));
        }
        frame = requestAnimationFrame(update);
      };
      frame = requestAnimationFrame(update);
    } catch { close(); setIsSupported(false); }
    return close;
  }, [stream, isActive, barCount]);
  return <div className={`flex flex-wrap items-center gap-3 ${className}`}>
    <div className="flex items-center gap-2 text-secondary"><Mic size={14}/><span className="text-xs">{isSupported ? label : 'Audio meter unavailable'}</span></div>
    <div ref={barsRef} className="flex items-center gap-1" aria-hidden="true">
      {Array.from({ length: barCount }, (_, i) => <div key={i} style={{ opacity: .2 }} className={`w-1 h-3 rounded-full ${i >= barCount * .75 ? 'bg-red-600' : i >= barCount * .5 ? 'bg-amber-600' : 'bg-emerald-600'}`}/>)}
    </div>
  </div>;
});
