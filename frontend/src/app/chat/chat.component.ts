import { Component, NgZone, inject, signal, WritableSignal, DestroyRef } from '@angular/core';
import { ChatService } from '../services/chat.service';
import { HttpClient } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

interface Message {
  id: number;
  role: 'user' | 'bot';
  text: string;
  loading?: boolean;
  createdAt?: string;
  copied?: boolean;
}

@Component({
  selector: 'app-chat',
  templateUrl: './chat.component.html',
    styleUrls: ['./chat.component.scss'],
  standalone: true,
  imports: [CommonModule, FormsModule]
})
export class ChatComponent {
  private http = inject(HttpClient);
  private chatService = inject(ChatService);
  private zone = inject(NgZone);
  private destroyRef = inject(DestroyRef);

  input: WritableSignal<string> = signal('');
  messages: WritableSignal<Message[]> = signal([]);
  private nextId = 1;
  private activeSources = new Map<number, EventSource>();
  private buffers = new Map<number, string>();
  // flushTimers maps message ID to timer ID
  private flushTimers = new Map<number, number>();
  private flushDelay = 80; //batch incoming chunks to reduce DOM churn

  backend = 'http://localhost:8000';

  sendStream() {
    const q = this.input().trim();
    if (!q) return;

    const userMsg: Message = { id: this.nextId++, role: 'user', text: q };
    this.appendMessage(userMsg);
    this.input.set('');

    const botId = this.nextId++;
    const botMsg: Message = { id: botId, role: 'bot', text: '', loading: true };
    this.appendMessage(botMsg);

    const es = this.chatService.streamPrompt(this.backend, q);
    this.activeSources.set(botId, es);

    es.onmessage = (e: MessageEvent) => {
      const data = String(e.data ?? '');
      // Buffer small chunks and flush after a short delay to reduce reflows
      const prevBuf = this.buffers.get(botId) ?? '';
      this.buffers.set(botId, prevBuf + data);
      if (!this.flushTimers.has(botId)) {
        const t = window.setTimeout(() => {
          const buf = this.buffers.get(botId) ?? '';
          this.buffers.delete(botId);
          this.flushTimers.delete(botId);
          if (buf) {
            this.zone.run(() => {
              this.updateMessageText(botId, (prev) => prev + buf);
              this.scrollToEnd();
            });
          }
        }, this.flushDelay) as unknown as number;
        this.flushTimers.set(botId, t);
      }
    };

    es.addEventListener('done', () => {
      // flush any buffered content immediately
      this.flushBuffer(botId);
      this.zone.run(() => {
        this.updateMessage(botId, { loading: false });
        this.scrollToEnd();
      });
      es.close();
      this.activeSources.delete(botId);
    });

    es.addEventListener('typing', () => {
      // server signalled typing; make sure UI shows the typing indicator
      this.zone.run(() => {
        this.updateMessage(botId, { loading: true });
        this.scrollToEnd();
      });
    });

    es.onerror = (err: Event | any) => {
      console.error('EventSource error', err);
      this.zone.run(() => {
        this.updateMessage(botId, { loading: false, text: (this.getMessageText(botId) || '') + '\n[ERROR] EventSource error' });
        this.scrollToEnd();
      });
      es.close();
      this.activeSources.delete(botId);
    };

    this.destroyRef.onDestroy(() => {
      es.close();
    });
  }

  sendOnce() {
    const q = this.input().trim();
    if (!q) return;
    this.appendMessage({ id: this.nextId++, role: 'user', text: q });
    this.input.set('');

    this.chatService.ask(this.backend, q).subscribe({
      next: (res: { answer: string }) => {
        this.appendMessage({ id: this.nextId++, role: 'bot', text: res.answer });
        this.scrollToEnd();
      },
      error: (err: any) => this.appendMessage({ id: this.nextId++, role: 'bot', text: '[ERROR] ' + (err?.message ?? String(err)) }),
    });
  }

  scrollToEnd() {
    setTimeout(() => {
      const el = document.querySelector('.conversation');
      if (el) el.scrollTop = el.scrollHeight;
    }, 10);
  }

  // Helpers for working with signals immutably
  private appendMessage(m: Message) {
    const now = new Date().toISOString();
    this.messages.update((arr) => [...arr, { ...m, createdAt: m.createdAt ?? now, copied: false }]);
  }

  private updateMessage(id: number, patch: Partial<Message>) {
    this.messages.update((arr) => arr.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  }

  private updateMessageText(id: number, textUpdater: (prev: string) => string) {
    this.messages.update((arr) =>
      arr.map((message) => (message.id === id ? { ...message, text: textUpdater(message.text) } : message))
    );
  }

  private getMessageText(id: number) {
    const message = this.messages().find((x) => x.id === id);
    return message ? message.text : '';
  }

  trackById(_: number, item: Message) {
    return item.id;
  }

  async copyMessage(id: number) {
    const message = this.messages().find((x) => x.id === id);
    if (!message) return;
    try {
      await navigator.clipboard.writeText(message.text || '');
      this.updateMessage(id, { copied: true });
      setTimeout(() => this.updateMessage(id, { copied: false }), 1500);
    } catch (e) {
      console.warn('Clipboard.writeText failed', e);
    }
  }

  stopStream(id: number) {
    const eventSource = this.activeSources.get(id);
    if (!eventSource) return;
    try {
      eventSource.close();
    } catch {}
    this.activeSources.delete(id);
    // flush any buffered text immediately, then mark stopped
    this.flushBuffer(id);
    const prev = this.getMessageText(id) || '';
    this.updateMessage(id, { loading: false, text: prev + '\n[Stopped]' });
  }

  private flushBuffer(id: number) {
    const buf = this.buffers.get(id);
    if (buf) {
      // cancel pending timer
      const t = this.flushTimers.get(id);
      if (t) {
        clearTimeout(t);
        this.flushTimers.delete(id);
      }
      this.buffers.delete(id);
      this.zone.run(() => {
        this.updateMessageText(id, (prev) => prev + buf);
      });
    }
  }

  onEnter(e: Event) {
    const ke = e as KeyboardEvent;
    if (!ke.shiftKey) {
      ke.preventDefault();
      this.sendStream();
    }
  }
}