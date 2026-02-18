const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, makeCacheableSignalKeyStore, Browsers } = require('@whiskeysockets/baileys');
const express = require('express');
const pino = require('pino');
const qrcode = require('qrcode-terminal');

const AGENT_URL = process.env.AGENT_URL || 'http://agent:8000';
const PORT = process.env.BRIDGE_PORT || 3000;
const OWNER_JID = process.env.OWNER_JID || '15197310464@s.whatsapp.net';
const logger = pino({ level: 'warn' });

let sock = null;

async function connectWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState('./auth');

    sock = makeWASocket({
        version: [2, 3000, 1027934701],
        browser: Browsers.macOS('Chrome'),
        auth: {
            creds: state.creds,
            keys: makeCacheableSignalKeyStore(state.keys, logger),
        },
        printQRInTerminal: false,
        logger,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
        if (qr) {
            console.log('\n=== Scan this QR code with WhatsApp ===\n');
            qrcode.generate(qr, { small: true });
            console.log('\n========================================\n');
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            console.log(`Connection closed. Status: ${statusCode}. Reconnecting: ${shouldReconnect}`);
            if (shouldReconnect) {
                setTimeout(connectWhatsApp, 3000);
            }
        } else if (connection === 'open') {
            console.log('Connected to WhatsApp');
        }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;

        for (const msg of messages) {
            if (!msg.message) continue;

            // Only respond to the owner
            const sender = msg.key.remoteJid || (msg.key.fromMe ? OWNER_JID : null);
            if (sender !== OWNER_JID) continue;

            const text = msg.message.conversation
                || msg.message.extendedTextMessage?.text
                || '';

            if (!text.trim()) continue;
            console.log(`[${sender}] ${text}`);

            try {
                const res = await fetch(`${AGENT_URL}/webhook`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sender, text }),
                });
                const data = await res.json();

                // Send text reply
                if (data.reply) {
                    await sock.sendMessage(sender, { text: data.reply });
                    console.log(`[reply -> ${sender}] ${data.reply.substring(0, 100)}...`);
                }

                // Send file attachment if present
                if (data.file) {
                    const buffer = Buffer.from(data.file.base64, 'base64');
                    await sock.sendMessage(sender, {
                        document: buffer,
                        mimetype: data.file.mimetype,
                        fileName: data.file.filename,
                    });
                    console.log(`[file -> ${sender}] ${data.file.filename}`);
                }
            } catch (err) {
                console.error(`Failed to process message: ${err.message}`);
                await sock.sendMessage(sender, { text: 'Sorry, I encountered an error. Please try again.' });
            }
        }
    });
}

// Express server for sending messages programmatically
const app = express();
app.use(express.json({ limit: '50mb' }));

app.post('/send', async (req, res) => {
    const { to, text } = req.body;
    if (!to || !text) return res.status(400).json({ error: 'Missing "to" or "text"' });

    try {
        await sock.sendMessage(to, { text });
        res.json({ status: 'sent' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.get('/health', (req, res) => {
    res.json({ status: 'ok', connected: !!sock?.user });
});

app.listen(PORT, () => {
    console.log(`Bridge HTTP server on port ${PORT}`);
    connectWhatsApp();
});
