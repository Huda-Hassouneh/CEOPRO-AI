import { randomBytes } from "node:crypto";
import tls, { type TLSSocket } from "node:tls";
import { createVerificationEmailContent } from "./verification-email.content.js";
import type { VerificationEmailInput } from "./email.types.js";

const SMTP_HOST = "smtp.gmail.com";
const SMTP_PORT = 465;
const SMTP_TIMEOUT_MS = 15_000;

type SmtpReply = { code: number; lines: string[] };
type ReplyWaiter = {
  resolve: (reply: SmtpReply) => void;
  reject: (error: Error) => void;
  timeout: NodeJS.Timeout;
};

class SmtpReplyReader {
  private buffer = "";
  private currentReply: string[] = [];
  private readonly queuedReplies: SmtpReply[] = [];
  private readonly waiters: ReplyWaiter[] = [];
  private failure: Error | undefined;

  constructor(socket: TLSSocket) {
    socket.on("data", (chunk: Buffer) => this.receive(chunk.toString("utf8")));
    socket.on("error", (error: Error) => this.fail(error));
    socket.on("close", () => this.fail(new Error("Gmail SMTP connection closed")));
  }

  read(): Promise<SmtpReply> {
    const reply = this.queuedReplies.shift();
    if (reply) return Promise.resolve(reply);
    if (this.failure) return Promise.reject(this.failure);

    return new Promise((resolve, reject) => {
      const waiter: ReplyWaiter = {
        resolve,
        reject,
        timeout: setTimeout(() => {
          this.fail(new Error("Gmail SMTP response timed out"));
        }, SMTP_TIMEOUT_MS)
      };
      this.waiters.push(waiter);
    });
  }

  private receive(chunk: string): void {
    this.buffer += chunk;
    let lineBreak = this.buffer.indexOf("\r\n");
    while (lineBreak >= 0) {
      const line = this.buffer.slice(0, lineBreak);
      this.buffer = this.buffer.slice(lineBreak + 2);
      this.currentReply.push(line);

      if (/^\d{3} /.test(line)) {
        const firstLine = this.currentReply[0] ?? line;
        const reply: SmtpReply = {
          code: Number(firstLine.slice(0, 3)),
          lines: this.currentReply
        };
        this.currentReply = [];
        const waiter = this.waiters.shift();
        if (waiter) {
          clearTimeout(waiter.timeout);
          waiter.resolve(reply);
        } else {
          this.queuedReplies.push(reply);
        }
      }
      lineBreak = this.buffer.indexOf("\r\n");
    }
  }

  private fail(error: Error): void {
    if (this.failure) return;
    this.failure = error;
    for (const waiter of this.waiters.splice(0)) {
      clearTimeout(waiter.timeout);
      waiter.reject(error);
    }
  }
}

function expectReply(reply: SmtpReply, expected: number | number[]): void {
  const codes = Array.isArray(expected) ? expected : [expected];
  if (!codes.includes(reply.code)) {
    throw new Error(`Gmail SMTP rejected a command (SMTP ${reply.code})`);
  }
}

async function sendCommand(
  socket: TLSSocket,
  replies: SmtpReplyReader,
  command: string,
  expected: number | number[]
): Promise<SmtpReply> {
  if (/[\r\n]/.test(command)) throw new Error("Invalid SMTP command");
  const pendingReply = replies.read();
  socket.write(`${command}\r\n`);
  const reply = await pendingReply;
  expectReply(reply, expected);
  return reply;
}

function encodeMimeBody(value: string): string {
  return Buffer.from(value, "utf8").toString("base64").match(/.{1,76}/g)?.join("\r\n") ?? "";
}

function createMimeMessage(input: VerificationEmailInput, sender: string): string {
  if (!/^[^\s<>@]+@[^\s<>@]+$/.test(input.email) || /[\r\n]/.test(input.email)) {
    throw new Error("Invalid verification email recipient");
  }

  const content = createVerificationEmailContent(input);
  const boundary = `ceopro_${randomBytes(16).toString("hex")}`;
  return [
    `From: CEO PRO <${sender}>`,
    `To: <${input.email}>`,
    `Subject: ${content.subject}`,
    "MIME-Version: 1.0",
    `Content-Type: multipart/alternative; boundary="${boundary}"`,
    "",
    `--${boundary}`,
    "Content-Type: text/plain; charset=UTF-8",
    "Content-Transfer-Encoding: base64",
    "",
    encodeMimeBody(content.text),
    `--${boundary}`,
    "Content-Type: text/html; charset=UTF-8",
    "Content-Transfer-Encoding: base64",
    "",
    encodeMimeBody(content.html),
    `--${boundary}--`,
    ""
  ].join("\r\n");
}

function dotStuff(message: string): string {
  return message.replace(/(^|\r\n)\./g, "$1..");
}

function getCredentials() {
  const user = process.env.GMAIL_SMTP_USER?.trim();
  const password = process.env.GMAIL_SMTP_APP_PASSWORD?.replace(/\s/g, "");
  if (!user) throw new Error("GMAIL_SMTP_USER is not configured");
  if (!password) throw new Error("GMAIL_SMTP_APP_PASSWORD is not configured");
  if (!/^[^\s<>@]+@[^\s<>@]+$/.test(user)) {
    throw new Error("GMAIL_SMTP_USER must be a valid Gmail address");
  }
  return { user, password };
}

export async function sendVerificationEmailWithGmail(
  input: VerificationEmailInput
): Promise<void> {
  const { user, password } = getCredentials();
  const socket = tls.connect({
    host: SMTP_HOST,
    port: SMTP_PORT,
    servername: SMTP_HOST,
    timeout: SMTP_TIMEOUT_MS
  });
  const replies = new SmtpReplyReader(socket);
  socket.setTimeout(SMTP_TIMEOUT_MS, () => {
    socket.destroy(new Error("Gmail SMTP connection timed out"));
  });

  try {
    await new Promise<void>((resolve, reject) => {
      socket.once("secureConnect", resolve);
      socket.once("error", reject);
    });
    expectReply(await replies.read(), 220);
    await sendCommand(socket, replies, "EHLO localhost", 250);
    await sendCommand(socket, replies, "AUTH LOGIN", 334);
    await sendCommand(socket, replies, Buffer.from(user).toString("base64"), 334);
    await sendCommand(socket, replies, Buffer.from(password).toString("base64"), 235);
    await sendCommand(socket, replies, `MAIL FROM:<${user}>`, 250);
    await sendCommand(socket, replies, `RCPT TO:<${input.email}>`, [250, 251]);
    await sendCommand(socket, replies, "DATA", 354);

    const pendingReply = replies.read();
    socket.write(`${dotStuff(createMimeMessage(input, user))}.\r\n`);
    expectReply(await pendingReply, 250);
    await sendCommand(socket, replies, "QUIT", 221);
  } finally {
    socket.end();
  }
}

export { createMimeMessage };
