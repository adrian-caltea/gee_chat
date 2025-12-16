import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface AskResponse {
  answer: string;
}

@Injectable({ providedIn: 'root' })
export class ChatService {
  private http = inject(HttpClient);

  constructor() {}

  ask(backend: string, question: string): Observable<AskResponse> {
    return this.http.post<AskResponse>(`${backend}/ask`, { question });
  }

  streamPrompt(backend: string, prompt: string): EventSource {
    return new EventSource(`${backend}/stream?prompt=${encodeURIComponent(prompt)}`);
  }
}
