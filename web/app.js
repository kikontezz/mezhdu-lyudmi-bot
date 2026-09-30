/* ===== «Между людьми» — Mini App ===== */

const tg = window.Telegram.WebApp;
tg.ready();
try { tg.expand(); } catch (e) {}

// вне Telegram подставляем dev-вход (работает только с DEV_FAKE_AUTH=1 на сервере)
const _dev = new URLSearchParams(location.search).get('dev');
const INIT_DATA = tg.initData || (_dev ? 'dev:' + _dev : 'dev:111');

const S = {
    me: null,
    screen: 'home',
    status: 'idle',      // idle | queued | chat | banned
    chatId: null,
    peer: null,
    lastMsg: 0,
    lastNote: 0,
    pollActive: false,
    typingTimer: null,
    reportReason: '',
};

/* ---------- API ---------- */

async function api(path, body) {
    const res = await fetch('/api' + path, {
        method: body ? 'POST' : 'GET',
        headers: {
            'Content-Type': 'application/json',
            'X-Telegram-Init-Data': INIT_DATA,
        },
        body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Ошибка сети');
    return data;
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function toast(text, ms = 2600) {
    const el = document.getElementById('toast');
    el.textContent = text;
    el.style.display = 'block';
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.style.display = 'none'; }, ms);
}

function haptic(kind) {
    try { tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(kind); } catch (e) {}
}

/* ---------- Навигация ---------- */

function show(name) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const el = document.getElementById('screen-' + name);
    if (el) el.classList.add('active');
    S.screen = name;

    if (name === 'profile') renderProfile();
    if (name === 'admin') adminTab('reports');

    const needPoll = ['search', 'found', 'chat'].includes(name);
    if (needPoll) startPoll(); else S.pollActive = false;
}

/* ---------- Инициализация ---------- */

async function init() {
    try {
        S.me = await api('/auth', { init_data: INIT_DATA });
    } catch (e) {
        document.getElementById('loader').innerHTML =
            '<div style="text-align:center;padding:30px;color:#fff">' +
            '😕 Не удалось войти.<br><br>Открой бота через команду /start</div>';
        return;
    }
    document.getElementById('loader').style.display = 'none';

    if (S.me.is_admin) {
        document.querySelectorAll('.admin-only').forEach(b => b.style.display = '');
    }
    if (S.me.banned) {
        toast('⛔ Ты заблокирован модератором', 5000);
    }
    const notifBox = document.getElementById('tg-notif');
    notifBox.checked = S.me.notify !== false;
    notifBox.addEventListener('change', async () => {
        try {
            await api('/profile', { notify: notifBox.checked });
            toast(notifBox.checked ? '🔔 Уведомления включены' : '🔕 Уведомления выключены');
        } catch (e) {
            toast('⚠️ ' + e.message);
        }
    });
    show('home');
}

/* ---------- Поиск и чат ---------- */

async function startSearch() {
    show('search');
    try {
        const r = await api('/queue', {});
        if (r.status === 'chat') {
            S.chatId = r.chat_id;
            S.peer = r.peer;
            showFound();
        }
    } catch (e) {
        toast('⚠️ ' + e.message);
        show('home');
    }
}

function showFound() {
    haptic('success');
    setAvatar(document.getElementById('found-avatar'), S.peer && S.peer.avatar);
    show('found');
}

async function cancelSearch() {
    try { await api('/cancel', {}); } catch (e) {}
    show('home');
}

function openChat() {
    setAvatar(document.getElementById('chat-avatar'), S.peer && S.peer.avatar);
    document.getElementById('chat-body').innerHTML =
        '<div class="day-pill">Сегодня</div>';
    show('chat');
    const input = document.getElementById('msg-input');
    setTimeout(() => input.focus(), 250);
}

async function leaveChat() {
    try { await api('/leave', {}); } catch (e) {}
    closeMenu();
    S.chatId = null;
    S.peer = null;
    S.status = 'idle';
    haptic('warning');
    show('ended');
}

async function blockPeer() {
    closeMenu();
    if (!confirm('Заблокировать собеседника? Вы больше никогда не встретитесь.')) return;
    try {
        await api('/block', {});
        toast('🚫 Собеседник заблокирован');
        haptic('warning');
        S.chatId = null;
        S.peer = null;
        S.status = 'idle';
        show('ended');
    } catch (e) {
        toast('⚠️ ' + e.message);
    }
}

/* ---------- Сообщения ---------- */

function nowHM(ts) {
    const d = ts ? new Date(ts * 1000) : new Date();
    return d.getHours().toString().padStart(2, '0') + ':' +
           d.getMinutes().toString().padStart(2, '0');
}

// id уже отрисованных сообщений — защита от дублей (оптимистичная отрисовка + poll)
const renderedIds = new Set();

function addMsg(m) {
    if (m.id) {
        if (renderedIds.has(m.id)) return;
        renderedIds.add(m.id);
    }
    const body = document.getElementById('chat-body');
    const mine = S.me && m.sender_id === S.me.tg_id;
    const div = document.createElement('div');
    div.className = 'msg ' + (mine ? 'out' : 'in');
    const text = document.createElement('span');
    text.textContent = m.text;
    const time = document.createElement('span');
    time.className = 'msg-time';
    time.textContent = nowHM(m.created_at);
    div.appendChild(text);
    div.appendChild(time);
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
}

async function sendMsg() {
    const input = document.getElementById('msg-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    try {
        const r = await api('/message', { text });
        S.lastMsg = Math.max(S.lastMsg, r.id);
        addMsg({ sender_id: S.me.tg_id, text, created_at: Date.now() / 1000, id: r.id });
        haptic('success');
    } catch (e) {
        toast('⚠️ ' + e.message);
        input.value = text;
    }
}

function onType() {
    clearTimeout(S.typingTimer);
    S.typingTimer = setTimeout(() => {
        if (S.screen === 'chat') api('/typing', {}).catch(() => {});
    }, 1200);
}

function voiceSoon() {
    toast('🎙 Голосовые сообщения появятся в следующем обновлении');
}

/* ---------- Жалоба ---------- */

function toggleChatMenu() {
    const m = document.getElementById('chat-menu');
    m.style.display = m.style.display === 'none' ? 'flex' : 'none';
}
function closeMenu() {
    document.getElementById('chat-menu').style.display = 'none';
}

function openReport() {
    closeMenu();
    // доказательства — последние сообщения чата
    const msgs = [...document.querySelectorAll('#chat-body .msg')].slice(-15);
    const lines = msgs.map(el => {
        const who = el.classList.contains('out') ? 'Я' : 'Собеседник';
        return who + ': ' + el.querySelector('span').textContent;
    });
    document.getElementById('report-evidence').value = lines.join('\n');
    document.getElementById('report-reason').value = '';
    document.querySelectorAll('#report-chips .chip').forEach(c => c.classList.remove('active'));
    show('report');
}

function closeReport() { show('chat'); }

async function sendReport() {
    const chip = document.querySelector('#report-chips .chip.active');
    const reason = chip
        ? chip.dataset.r + (document.getElementById('report-reason').value.trim()
            ? ': ' + document.getElementById('report-reason').value.trim()
            : '')
        : document.getElementById('report-reason').value.trim();
    if (!reason) {
        toast('Выбери причину или опиши ситуацию');
        return;
    }
    try {
        await api('/report', {
            reason,
            evidence: document.getElementById('report-evidence').value,
            chat_id: S.chatId,
        });
        haptic('warning');
        toast('📨 Жалоба отправлена модератору');
        show('chat');
    } catch (e) {
        toast('⚠️ ' + e.message);
    }
}

/* ---------- Polling ---------- */

async function startPoll() {
    if (S.pollActive) return;
    S.pollActive = true;
    while (S.pollActive) {
        try {
            const p = await api(
                `/poll?since_msg=${S.lastMsg}&since_note=${S.lastNote}&timeout=25`);
            handlePoll(p);
        } catch (e) {
            await sleep(3000);
        }
    }
}

function handlePoll(p) {
    // уведомления — только двигаем курсор (в TG они уходят отдельно)
    if (p.notifications && p.notifications.length) {
        p.notifications.forEach(n => { S.lastNote = Math.max(S.lastNote, n.id); });
    }

    if (p.status === 'banned') {
        S.pollActive = false;
        toast('⛔ Ты заблокирован модератором: ' + (p.reason || ''), 5000);
        show('home');
        return;
    }

    const prev = S.status;
    S.status = p.status;

    if (p.status === 'chat') {
        S.chatId = p.chat_id;
        S.peer = p.peer;

        if (prev !== 'chat') {
            if (S.screen === 'search') showFound();
            if (S.screen === 'found' && !document.getElementById('screen-found').classList.contains('active')) {
                showFound();
            }
        }
        if (p.messages && p.messages.length && S.screen === 'chat') {
            p.messages.forEach(m => {
                addMsg(m);
                S.lastMsg = Math.max(S.lastMsg, m.id);
            });
        } else if (p.messages) {
            p.messages.forEach(m => { S.lastMsg = Math.max(S.lastMsg, m.id); });
        }
        const typing = document.getElementById('typing');
        typing.style.visibility = p.peer_typing ? 'visible' : 'hidden';
        const st = document.getElementById('peer-status');
        st.textContent = p.peer_typing ? 'печатает…' : 'Онлайн';

    } else if (p.status === 'idle') {
        if (prev === 'chat') {
            S.pollActive = false;
            S.chatId = null;
            S.peer = null;
            haptic('warning');
            toast('Собеседник покинул чат');
            show('ended');
        } else if (prev === 'queued' && S.screen === 'search') {
            // нас выкинуло из очереди
            show('home');
        }
    }
    // queued — просто ждём дальше
}

/* ---------- Профиль ---------- */

function setAvatar(el, dataUrl) {
    el.style.backgroundImage = dataUrl ? `url(${dataUrl})` : '';
}

function renderProfile() {
    if (!S.me) return;
    document.getElementById('profile-name').textContent = 'Аноним #' + S.me.anon_num;
    setAvatar(document.getElementById('profile-avatar'), S.me.avatar);
}

function pickAvatar() {
    document.getElementById('avatar-file').click();
}

function resizeAvatar(file, cb) {
    const img = new Image();
    img.onload = () => {
        const size = 160;
        const c = document.createElement('canvas');
        c.width = c.height = size;
        const ctx = c.getContext('2d');
        const min = Math.min(img.width, img.height);
        ctx.drawImage(img,
            (img.width - min) / 2, (img.height - min) / 2, min, min,
            0, 0, size, size);
        cb(c.toDataURL('image/jpeg', 0.82));
    };
    img.src = URL.createObjectURL(file);
}

async function onAvatarFile(ev) {
    const file = ev.target.files[0];
    if (!file) return;
    resizeAvatar(file, async (dataUrl) => {
        try {
            S.me = await api('/profile', { avatar: dataUrl });
            renderProfile();
            toast('✅ Аватарка обновлена');
        } catch (e) {
            toast('⚠️ ' + e.message);
        }
    });
    ev.target.value = '';
}

/* ---------- Настройки ---------- */

function clearLocal() {
    localStorage.clear();
    toast('🧹 Локальная история очищена');
}

/* ---------- Админка ---------- */

let adminTabName = 'reports';

function adminTab(name) {
    adminTabName = name;
    document.getElementById('tab-reports').classList.toggle('active', name === 'reports');
    document.getElementById('tab-banned').classList.toggle('active', name === 'banned');
    loadAdmin();
}

async function loadAdmin() {
    const list = document.getElementById('admin-list');
    list.innerHTML = '<div class="muted">Загрузка…</div>';
    try {
        if (adminTabName === 'reports') {
            const rows = await api('/admin/reports?status=new');
            if (!rows.length) { list.innerHTML = '<div class="muted">Новых жалоб нет 🎉</div>'; return; }
            list.innerHTML = '';
            rows.forEach(r => {
                const card = document.createElement('div');
                card.className = 'report-card';
                const title = document.createElement('div');
                title.className = 'rc-title';
                title.textContent = `Жалоба #${r.id}: Аноним #${r.reporter_anon} → Аноним #${r.accused_anon}`;
                const reason = document.createElement('div');
                reason.textContent = '📌 ' + r.reason;
                const ev = document.createElement('div');
                ev.className = 'rc-ev';
                ev.textContent = (r.evidence || '').slice(0, 500);
                const actions = document.createElement('div');
                actions.className = 'report-actions';

                const ban = document.createElement('button');
                ban.className = 'btn btn-danger';
                ban.textContent = '⛔ Забанить';
                ban.onclick = async () => {
                    if (!confirm(`Забанить Аноним #${r.accused_anon}?`)) return;
                    await api(`/admin/users/${r.accused_id}/ban`, { reason: r.reason });
                    await api(`/admin/reports/${r.id}/resolve`, {});
                    toast('⛔ Пользователь забанен');
                    loadAdmin();
                };
                const skip = document.createElement('button');
                skip.className = 'btn btn-soft';
                skip.textContent = '✅ Принято';
                skip.onclick = async () => {
                    await api(`/admin/reports/${r.id}/resolve`, {});
                    loadAdmin();
                };
                actions.appendChild(ban);
                actions.appendChild(skip);
                card.appendChild(title);
                card.appendChild(reason);
                if (r.evidence) card.appendChild(ev);
                card.appendChild(actions);
                list.appendChild(card);
            });
        } else {
            const rows = await api('/admin/banned');
            if (!rows.length) { list.innerHTML = '<div class="muted">Забаненных нет</div>'; return; }
            list.innerHTML = '';
            rows.forEach(u => {
                const card = document.createElement('div');
                card.className = 'report-card';
                const title = document.createElement('div');
                title.className = 'rc-title';
                title.textContent = `Аноним #${u.anon_num}`;
                const reason = document.createElement('div');
                reason.textContent = '📌 ' + (u.banned_reason || '—');
                const actions = document.createElement('div');
                actions.className = 'report-actions';
                const un = document.createElement('button');
                un.className = 'btn btn-soft';
                un.textContent = '✅ Разбанить';
                un.onclick = async () => {
                    await api(`/admin/users/${u.tg_id}/unban`, {});
                    toast('Пользователь разбанен');
                    loadAdmin();
                };
                actions.appendChild(un);
                card.appendChild(title);
                card.appendChild(reason);
                card.appendChild(actions);
                list.appendChild(card);
            });
        }
    } catch (e) {
        list.innerHTML = '<div class="muted">⚠️ ' + e.message + '</div>';
    }
}

/* ---------- Обработчики ---------- */

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('msg-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') sendMsg();
    });
    document.getElementById('msg-input').addEventListener('input', onType);
    document.getElementById('avatar-file').addEventListener('change', onAvatarFile);

    document.querySelectorAll('#report-chips .chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('#report-chips .chip')
                .forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
        });
    });

    // клик вне меню чата — закрыть
    document.getElementById('screen-chat').addEventListener('click', e => {
        if (!e.target.closest('.chat-menu') && !e.target.closest('.chat-menu-btn')) {
            closeMenu();
        }
    });

    init();
});
