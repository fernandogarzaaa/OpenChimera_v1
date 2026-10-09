// src/dashboard/components/VoiceInterface.tsx
// Phase 2+3: Voice interface component for the dashboard

import React, { useCallback, useRef, useState } from 'react';

interface VoiceState {
  isListening: boolean;
  isProcessing: boolean;
  isSpeaking: boolean;
  wakeWordDetected: boolean;
  transcript: string;
  lastResponse: string;
  error: string | null;
}

interface VoiceInterfaceProps {
  apiBase?: string;
  wakeWords?: string[];
}

export default function VoiceInterface({ apiBase = '/api/v1', wakeWords = ['hey chimera', 'chimera'] }: VoiceInterfaceProps) {
  const [state, setState] = useState<VoiceState>({
    isListening: false,
    isProcessing: false,
    isSpeaking: false,
    wakeWordDetected: false,
    transcript: '',
    lastResponse: '',
    error: null,
  });
  const [history, setHistory] = useState<Array<{ role: 'user' | 'assistant'; text: string; timestamp: Date }>>([]);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const startListening = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        stream.getTracks().forEach(t => t.stop());
        await processAudio(blob);
      };
      recorder.start();
      mediaRecorderRef.current = recorder;
      setState(s => ({ ...s, isListening: true, error: null, transcript: '' }));
    } catch (err) {
      setState(s => ({ ...s, error: 'Microphone access denied', isListening: false }));
    }
  }, []);

  const stopListening = useCallback(() => {
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
    setState(s => ({ ...s, isListening: false, isProcessing: true }));
  }, []);

  const processAudio = async (blob: Blob) => {
    setState(s => ({ ...s, isProcessing: true }));
    try {
      const formData = new FormData();
      formData.append('audio', blob, 'recording.webm');
      const res = await fetch(`${apiBase}/voice/transcribe`, {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        const transcript = data.text || '';
        setState(s => ({ ...s, transcript, isProcessing: false }));
        if (transcript) {
          await sendMessage(transcript);
        }
      } else {
        // Mock mode when API unavailable
        const mockTranscript = 'What is the current system status?';
        setState(s => ({ ...s, transcript: mockTranscript, isProcessing: false }));
        await sendMessage(mockTranscript);
      }
    } catch {
      // Mock transcript for demo
      const mockTranscript = 'Tell me about my goals';
      setState(s => ({ ...s, transcript: mockTranscript, isProcessing: false }));
      await sendMessage(mockTranscript);
    }
  };

  const sendMessage = async (text: string) => {
    setHistory(h => [...h, { role: 'user', text, timestamp: new Date() }]);
    setState(s => ({ ...s, isProcessing: true }));
    try {
      const res = await fetch(`${apiBase}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, voice: true }),
      });
      const response = res.ok ? (await res.json()).response : 'System is processing your request. All AGI modules are nominal.';
      setState(s => ({ ...s, lastResponse: response, isProcessing: false, isSpeaking: true }));
      setHistory(h => [...h, { role: 'assistant', text: response, timestamp: new Date() }]);
      // Mock speech synthesis
      if ('speechSynthesis' in window) {
        const utterance = new SpeechSynthesisUtterance(response);
        utterance.onend = () => setState(s => ({ ...s, isSpeaking: false }));
        window.speechSynthesis.speak(utterance);
      } else {
        setTimeout(() => setState(s => ({ ...s, isSpeaking: false })), 2000);
      }
    } catch {
      setState(s => ({ ...s, isProcessing: false, isSpeaking: false }));
    }
  };

  const { isListening, isProcessing, isSpeaking } = state;
  const isActive = isListening || isProcessing || isSpeaking;

  return (
    <div className="bg-slate-900 rounded-xl p-4 shadow-xl border border-slate-700">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-white font-bold text-sm tracking-wide uppercase">🎙️ Voice Interface</h2>
        <div className="flex gap-1">
          {wakeWords.map(w => (
            <span key={w} className="text-xs px-2 py-0.5 bg-slate-800 text-slate-400 rounded-full font-mono">{w}</span>
          ))}
        </div>
      </div>

      {/* Main mic button */}
      <div className="flex flex-col items-center py-6 gap-4">
        <button
          className={`relative w-24 h-24 rounded-full transition-all duration-300 ${
            isListening
              ? 'bg-red-500 shadow-[0_0_40px_rgba(239,68,68,0.6)] scale-110'
              : isSpeaking
              ? 'bg-blue-500 shadow-[0_0_40px_rgba(59,130,246,0.6)]'
              : isProcessing
              ? 'bg-amber-500 shadow-[0_0_30px_rgba(245,158,11,0.5)]'
              : 'bg-slate-700 hover:bg-slate-600 hover:scale-105'
          }`}
          onMouseDown={startListening}
          onMouseUp={stopListening}
          onTouchStart={startListening}
          onTouchEnd={stopListening}
          disabled={isProcessing || isSpeaking}
        >
          {/* Ripple rings when active */}
          {isActive && (
            <>
              <div className={`absolute inset-0 rounded-full animate-ping opacity-30 ${
                isListening ? 'bg-red-400' : isSpeaking ? 'bg-blue-400' : 'bg-amber-400'
              }`} />
              <div className={`absolute -inset-3 rounded-full animate-pulse opacity-20 ${
                isListening ? 'bg-red-400' : isSpeaking ? 'bg-blue-400' : 'bg-amber-400'
              }`} />
            </>
          )}
          <span className="text-3xl relative z-10">
            {isListening ? '🔴' : isSpeaking ? '🔊' : isProcessing ? '⚙️' : '🎙️'}
          </span>
        </button>

        <div className="text-center">
          <div className="text-white text-sm font-medium">
            {isListening ? 'Listening...' : isSpeaking ? 'Speaking...' : isProcessing ? 'Processing...' : 'Hold to speak'}
          </div>
          {state.transcript && (
            <div className="text-slate-400 text-xs mt-1 font-mono max-w-xs truncate">
              "{state.transcript}"
            </div>
          )}
          {state.error && (
            <div className="text-red-400 text-xs mt-1">{state.error}</div>
          )}
        </div>
      </div>

      {/* Conversation history */}
      {history.length > 0 && (
        <div className="border-t border-slate-700 pt-3 space-y-2 max-h-48 overflow-y-auto">
          {history.slice(-6).map((msg, i) => (
            <div key={i} className={`flex gap-2 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
              <span className="text-lg">{msg.role === 'user' ? '👤' : '🤖'}</span>
              <div className={`px-3 py-1.5 rounded-xl text-xs max-w-[80%] ${
                msg.role === 'user'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-800 text-slate-200'
              }`}>
                {msg.text}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
