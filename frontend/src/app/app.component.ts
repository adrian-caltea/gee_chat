import { Component, OnInit } from '@angular/core';
import { ChatComponent } from './chat/chat.component';

@Component({
  selector: 'app-root',
  template: `<app-chat></app-chat>`,
  standalone: true,
  imports: [ChatComponent]
})
export class AppComponent implements OnInit {
  ngOnInit() {
    console.log('AppComponent initialized');
  }
}