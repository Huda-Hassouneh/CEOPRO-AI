export class WebSocketClient {
  constructor(url = import.meta.env.VITE_WS_URL || 'ws://localhost:8000') {
    this.url = url;
    this.socket = null;
  }

  connect() {
    if (!this.socket) {
      this.socket = new WebSocket(this.url);
    }
    return this.socket;
  }

  disconnect() {
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  }

  send(payload) {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
    }
  }
}
