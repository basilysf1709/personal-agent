const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, makeCacheableSignalKeyStore, Browsers } = require('@whiskeysockets/baileys');
const express = require('express');
const pino = require('pino');
const qrcode = require('qrcode-terminal');

const AGENT_URL = process.env.AGENT_URL || 'http://agent:8000';
const PORT = process.env.BRIDGE_PORT || 3000;
const ALLOWED_JIDS = new Set((process.env.ALLOWED_JIDS || '15197310464,966570104802').split(',').map(n => n.trim() + '@s.whatsapp.net'));
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

            // Only respond to allowed numbers
            const sender = msg.key.remoteJid;
            if (!ALLOWED_JIDS.has(sender)) continue;

            // Extract text from various message types
            const text = msg.message.conversation
                || msg.message.extendedTextMessage?.text
                || msg.message.documentWithCaptionMessage?.message?.documentMessage?.caption
                || msg.message.documentMessage?.caption
                || msg.message.imageMessage?.caption
                || '';

            // Extract document/image if attached
            const docMsg = msg.message.documentWithCaptionMessage?.message?.documentMessage
                || msg.message.documentMessage;
            const imgMsg = msg.message.imageMessage;

            if (!text.trim() && !docMsg && !imgMsg) continue;
            console.log(`[${sender}] ${text || '(attachment)'}`);

            try {
                // Download attachment if present
                let attachment = null;
                const mediaMsg = docMsg || imgMsg;
                if (mediaMsg) {
                    try {
                        const { downloadMediaMessage } = require('@whiskeysockets/baileys');
                        const buffer = await downloadMediaMessage(msg, 'buffer', {}, { logger, reuploadRequest: sock.updateMediaMessage });
                        attachment = {
                            base64: buffer.toString('base64'),
                            filename: docMsg?.fileName || 'image.jpg',
                            mimetype: mediaMsg.mimetype || 'application/octet-stream',
                        };
                        console.log(`[attachment] ${attachment.filename} (${attachment.mimetype})`);
                    } catch (dlErr) {
                        console.error(`Failed to download attachment: ${dlErr.message}`);
                    }
                }

                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 360000);
                const res = await fetch(`${AGENT_URL}/webhook`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sender, text: text || '(see attached file)', attachment }),
                    signal: controller.signal,
                });
                clearTimeout(timeout);
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
