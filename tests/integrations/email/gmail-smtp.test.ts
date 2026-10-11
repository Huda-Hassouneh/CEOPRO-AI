import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test, { type TestContext } from "node:test";
import type { TLSSocket } from "node:tls";
import { sendVerificationEmailWithGmail } from "../../../src/integrations/email/gmail-smtp.client.js";

function smtpSocket(options: { rejectRecipient?: boolean } = {}) {
  const socket = new EventEmitter() as EventEmitter & {
    write: (chunk: string) => boolean;
    setTimeout: (_ms: number, _callback?: () => void) => unknown;
    end: () => void;
    destroy: (error?: Error) => void;
  };
  const writes: string[] = [];
  let inMessage = false;
  let ended = false;
  socket.write = (chunk) => {
    writes.push(chunk);
    if (inMessage) {
      inMessage = false;
      queueMicrotask(() => socket.emit("data", Buffer.from("250 message accepted\r\n")));
      return true;
    }
    const command = chunk.trim();
    let reply: string;
    if (command === "EHLO localhost") reply = "250-localhost\r\n250 AUTH LOGIN\r\n";
    else if (command === "AUTH LOGIN") reply = "334 VXNlcm5hbWU6\r\n";
    else if (command === Buffer.from("sender@gmail.test").toString("base64")) reply = "334 UGFzc3dvcmQ6\r\n";
    else if (command === Buffer.from("app-password-test").toString("base64")) reply = "235 authenticated\r\n";
    else if (command.startsWith("MAIL FROM:")) reply = "250 sender accepted\r\n";
    else if (command.startsWith("RCPT TO:")) reply = options.rejectRecipient ? "550 recipient rejected\r\n" : "250 recipient accepted\r\n";
    else if (command === "DATA") {
      inMessage = true;
      reply = "354 send message\r\n";
    } else if (command === "QUIT") reply = "221 bye\r\n";
    else throw new Error(`Unexpected fake SMTP command: ${command}`);
    queueMicrotask(() => socket.emit("data", Buffer.from(reply)));
    return true;
  };
  socket.setTimeout = () => socket;
  socket.end = () => { ended = true; };
  socket.destroy = (error) => { if (error) socket.emit("error", error); };

  return {
    socket: socket as unknown as TLSSocket,
    writes,
    get ended() { return ended; },
    connect: () => {
      queueMicrotask(() => {
        socket.emit("secureConnect");
        socket.emit("data", Buffer.from("220 smtp.gmail.test ESMTP\r\n"));
      });
      return socket as unknown as TLSSocket;
    }
  };
}

function setCredentials(t: TestContext) {
  const oldUser = process.env.GMAIL_SMTP_USER;
  const oldPassword = process.env.GMAIL_SMTP_APP_PASSWORD;
  process.env.GMAIL_SMTP_USER = "sender@gmail.test";
  process.env.GMAIL_SMTP_APP_PASSWORD = "app-password-test";
  t.after(() => {
    if (oldUser === undefined) delete process.env.GMAIL_SMTP_USER;
    else process.env.GMAIL_SMTP_USER = oldUser;
    if (oldPassword === undefined) delete process.env.GMAIL_SMTP_APP_PASSWORD;
    else process.env.GMAIL_SMTP_APP_PASSWORD = oldPassword;
  });
}

const input = { email: "person@example.test", fullName: "Test Person", token: "a".repeat(64) };

test("Gmail SMTP client completes a fake TLS SMTP exchange and sends MIME alternatives", async (t) => {
  setCredentials(t);
  const fake = smtpSocket();
  await sendVerificationEmailWithGmail(input, { connect: () => fake.connect() });

  const transcript = fake.writes.join("");
  assert.match(transcript, /AUTH LOGIN\r\n/);
  assert.match(transcript, /multipart\/alternative/);
  assert.match(transcript, /To: <person@example\.test>/);
  assert.match(transcript, new RegExp(Buffer.from("app-password-test").toString("base64")));
  assert.doesNotMatch(transcript, /app-password-test/);
  assert.equal(fake.ended, true);
});

test("Gmail SMTP client rejects a recipient error and closes the connection", async (t) => {
  setCredentials(t);
  const fake = smtpSocket({ rejectRecipient: true });
  await assert.rejects(
    sendVerificationEmailWithGmail(input, { connect: () => fake.connect() }),
    /SMTP 550/
  );
  assert.equal(fake.ended, true);
});
