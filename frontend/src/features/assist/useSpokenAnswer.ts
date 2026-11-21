/**
 * Voice mode: speak the answer while it streams in.
 *
 * - Phone has a voice for the language: each finished line is spoken as soon as it arrives
 *   (safety line first), so the technician hears step 1 while step 3 is still being written.
 * - No phone voice (common for Odia, Punjabi…): when the answer is complete, Sarvam Bulbul reads all of it
 *   (POST /assist/queries/:id/tts, cached on the server).
 * - "No answer": says the no-answer sentence so the technician knows without looking.
 * Needs primeSpeech() to have run inside the tap that sent the question.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSpeech, type QueryStatus } from './assistApi';
import { speakLine } from './parseAnswer';
import { canSpeak, findVoice, sharedAudio, speakBrowser, voicesReady } from './speech';

interface Opts {
  enabled: boolean;
  lang: string;
  text: string;                       // streamed answer so far
  phase: 'idle' | 'streaming' | 'done' | 'error';
  status: QueryStatus | null;
  queryId: string | null;
  words: { safety: string; check: string };
  noAnswerText: string;
}

export function useSpokenAnswer({ enabled, lang, text, phase, status, queryId, words, noAnswerText }: Opts) {
  const [speaking, setSpeaking] = useState(false);
  const spokenLines = useRef(0);
  const pending = useRef(0);
  const stopped = useRef(false);
  const serverStarted = useRef(false);
  const noAnswerSaid = useRef(false);
  const voice = useRef<SpeechSynthesisVoice | null | undefined>(undefined);   // undefined = not looked up yet
  const urlRef = useRef<string | null>(null);

  const say = useCallback((sentence: string) => {
    if (!voice.current) return;
    const u = new SpeechSynthesisUtterance(sentence);
    u.voice = voice.current;
    u.lang = voice.current.lang;
    u.rate = 0.95;
    pending.current += 1;
    setSpeaking(true);
    const finish = () => {
      pending.current = Math.max(0, pending.current - 1);
      if (pending.current === 0) setSpeaking(false);
    };
    u.onend = finish;
    u.onerror = finish;
    window.speechSynthesis.speak(u);
  }, []);

  const stop = useCallback(() => {
    stopped.current = true;
    pending.current = 0;
    if (canSpeak()) window.speechSynthesis.cancel();
    sharedAudio().pause();
    setSpeaking(false);
  }, []);

  // A new question starts: reset everything.
  useEffect(() => {
    if (phase === 'streaming' && text === '') {
      spokenLines.current = 0;
      pending.current = 0;
      stopped.current = false;
      serverStarted.current = false;
      noAnswerSaid.current = false;
    }
  }, [phase, text]);

  useEffect(() => {
    if (!enabled || stopped.current || phase === 'idle') return;
    let cancelled = false;
    (async () => {
      if (voice.current === undefined) {
        await voicesReady();
        voice.current = findVoice(lang);
      }
      if (cancelled || stopped.current) return;

      if (voice.current) {
        const lines = text.split('\n');
        const finished = phase === 'done' ? lines : lines.slice(0, -1);   // the last line may still be growing
        for (let i = spokenLines.current; i < finished.length; i++) {
          const sentence = speakLine(finished[i], words);
          if (sentence) say(sentence);
        }
        spokenLines.current = Math.max(spokenLines.current, finished.length);
        if (phase === 'done' && status === 'no_answer' && !noAnswerSaid.current) {
          noAnswerSaid.current = true;
          say(noAnswerText);
        }
        return;
      }

      // No phone voice: let Sarvam read the finished answer.
      if (phase === 'done' && status === 'answered' && queryId && !serverStarted.current) {
        serverStarted.current = true;
        try {
          const speech = await fetchSpeech(queryId);
          if (stopped.current) return;
          if (!(speech instanceof Blob)) {
            // Both server voices failed: the browser speaks with its own engine.
            const body = text.replace(/\[[EMH]\d+\]/g, '').replace(/\s+/g, ' ').trim();
            setSpeaking(speakBrowser(body, speech.lang || lang, () => setSpeaking(false)));
            return;
          }
          if (urlRef.current) URL.revokeObjectURL(urlRef.current);
          urlRef.current = URL.createObjectURL(speech);
          const a = sharedAudio();
          a.src = urlRef.current;
          a.onended = () => setSpeaking(false);
          a.onerror = () => setSpeaking(false);
          await a.play();
          setSpeaking(true);
        } catch {
          setSpeaking(false);       // reading aloud is optional; the text is on screen
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, lang, text, phase, status, queryId, words, noAnswerText, say]);

  // Leaving the screen stops the voice.
  useEffect(() => () => {
    if (canSpeak()) window.speechSynthesis.cancel();
    sharedAudio().pause();
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
  }, []);

  return { speaking, stop };
}
