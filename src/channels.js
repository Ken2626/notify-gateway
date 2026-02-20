function formatMarkdownForWecom(text) {
  return text.replace(/\n/g, "\n");
}

async function doFetch(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  return { response, text };
}

function resolveServerChanUrl(sendKey) {
  const normalized = String(sendKey || "").trim();
  if (!normalized) return "";

  if (normalized.startsWith("sctp")) {
    const matched = normalized.match(/^sctp(\d+)t/i);
    if (matched && matched[1]) {
      return `https://${matched[1]}.push.ft07.com/send/${normalized}.send`;
    }
  }

  return `https://sctapi.ftqq.com/${normalized}.send`;
}

async function sendTg(message, config) {
  const token = config.channelCreds.tgBotToken;
  const chatId = config.channelCreds.tgChatId;
  if (!token || !chatId) {
    return { skipped: true, reason: "telegram credentials missing" };
  }

  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const payload = {
    chat_id: chatId,
    text: `${message.title}\n\n${message.body}`,
    disable_web_page_preview: true,
  };

  const { response, text } = await doFetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`telegram request failed (${response.status}): ${text}`);
  }

  const data = text ? JSON.parse(text) : { ok: false };
  if (!data.ok) {
    throw new Error(`telegram api returned non-ok: ${text}`);
  }

  return { skipped: false };
}

async function sendWecom(message, config) {
  const webhookUrl = config.channelCreds.wecomWebhookUrl;
  if (!webhookUrl) {
    return { skipped: true, reason: "wecom webhook missing" };
  }

  const payload = {
    msgtype: "markdown",
    markdown: {
      content: formatMarkdownForWecom(`## ${message.title}\n${message.body}`),
    },
  };

  const { response, text } = await doFetch(webhookUrl, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`wecom request failed (${response.status}): ${text}`);
  }

  const data = text ? JSON.parse(text) : {};
  if (Number(data.errcode) !== 0) {
    throw new Error(`wecom api returned errcode=${data.errcode}: ${text}`);
  }

  return { skipped: false };
}

async function sendServerchan(message, config) {
  const sendKey = config.channelCreds.serverchanSendKey;
  if (!sendKey) {
    return { skipped: true, reason: "serverchan sendkey missing" };
  }

  const url = resolveServerChanUrl(sendKey);
  const body = new URLSearchParams({
    title: message.title,
    desp: message.body,
  });

  const { response, text } = await doFetch(url, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body,
  });

  if (!response.ok) {
    throw new Error(`serverchan request failed (${response.status}): ${text}`);
  }

  const data = text ? JSON.parse(text) : {};
  if (Number(data.code) !== 0) {
    throw new Error(`serverchan api returned code=${data.code}: ${text}`);
  }

  return { skipped: false };
}

export async function sendByChannel(channel, message, config) {
  if (channel === "tg") return sendTg(message, config);
  if (channel === "wecom") return sendWecom(message, config);
  if (channel === "serverchan") return sendServerchan(message, config);
  return { skipped: true, reason: `unsupported channel: ${channel}` };
}
