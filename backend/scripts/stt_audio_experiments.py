"""Experimental audio-only preprocessing. Not automatically applied to candidate recordings."""
import numpy as np
from scipy import signal,ndimage

def preprocess(samples,mode):
    x=samples.astype(np.float32)
    if mode=='none':return x
    if mode in ('highpass','gate'):
        x=signal.sosfiltfilt(signal.butter(3,120,fs=16000,btype='highpass',output='sos'),x)
    if mode=='gate':
        _,_,z=signal.stft(x,fs=16000,nperseg=512,noverlap=384)
        power=np.abs(z)**2
        # Lower temporal quantile estimates steady fan energy, not speech content.
        noise=np.percentile(power,15,axis=1,keepdims=True)
        gain=np.maximum(.18,np.sqrt(np.maximum(power-1.2*noise,0)/(power+1e-12)))
        gain=ndimage.uniform_filter(gain,size=(3,5))
        _,x=signal.istft(z*gain,fs=16000,nperseg=512,noverlap=384)
        x=x[:len(samples)]
    rms=float(np.sqrt(np.mean(x*x)));peak=float(np.max(np.abs(x)))
    # Limited gain avoids clipping; it cannot restore missing signal or improve SNR by itself.
    factor=min(4.0,.1/max(rms,1e-9),.95/max(peak,1e-9))
    return (x*factor).astype(np.float32)
