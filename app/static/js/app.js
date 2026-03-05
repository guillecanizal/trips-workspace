/* Alpine.js components for Trip Planner */

document.addEventListener('alpine:init', () => {

  /* ── Chat Panel ── */
  Alpine.data('chatPanel', (tripId, dayId) => ({
    tripId,
    dayId,
    messages: [],
    input: '',
    loading: false,
    statusText: 'Thinking...',
    _controller: null,
    panelHeight: Math.round(window.innerHeight * 0.33),
    minimized: false,
    _prevHeight: 0,

    init() {
      const savedMin = localStorage.getItem('chat_minimized');
      if (savedMin !== null) this.minimized = savedMin === 'true';
      const savedH = localStorage.getItem('chat_height');
      if (savedH !== null) this.panelHeight = parseInt(savedH, 10) || this.panelHeight;
      this.$watch('minimized', v => localStorage.setItem('chat_minimized', v));
      this.$watch('panelHeight', v => localStorage.setItem('chat_height', v));
    },

    toggleMinimize() {
      if (this.minimized) {
        this.panelHeight = this._prevHeight || Math.round(window.innerHeight * 0.33);
        this.minimized = false;
        this.$nextTick(() => this.scrollToBottom());
      } else {
        this._prevHeight = this.$refs.panel.offsetHeight;
        this.minimized = true;
      }
    },

    startDrag(e) {
      if (this.minimized) return;
      e.preventDefault();
      const startY = e.clientY;
      const startH = this.$refs.panel.offsetHeight;
      const onMove = (ev) => {
        const delta = startY - ev.clientY;
        this.panelHeight = Math.round(
          Math.max(120, Math.min(window.innerHeight * 0.85, startH + delta))
        );
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    },

    sendMessage() {
      const text = this.input.trim();
      if (!text || this.loading) return;
      this.messages.push({ role: 'user', content: text });
      this.input = '';
      this.loading = true;
      this.statusText = 'Thinking...';
      this.$nextTick(() => this.scrollToBottom());
      this._streamAgent(text);
    },

    async _streamAgent(message) {
      const controller = new AbortController();
      this._controller = controller;
      const body = { trip_id: this.tripId, message };
      if (this.dayId) body.day_id = this.dayId;

      try {
        const resp = await fetch('/agent/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        if (!resp.ok) throw new Error('Request failed');

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          buffer = parts.pop();
          for (const part of parts) {
            if (!part.startsWith('data: ')) continue;
            const dataStr = part.slice(6).trim();
            if (dataStr === '[DONE]') break;
            try {
              const evt = JSON.parse(dataStr);
              this._handleEvent(evt);
            } catch (e) { /* ignore */ }
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          this.messages.push({ role: 'assistant', content: err.message || 'Error' });
        }
      } finally {
        this.loading = false;
        this._controller = null;
        this.$nextTick(() => this.scrollToBottom());
      }
    },

    _handleEvent(evt) {
      if (evt.type === 'status') {
        this.statusText = evt.message;
      } else if (evt.type === 'text') {
        this.messages.push({ role: 'assistant', content: evt.content });
        this.$nextTick(() => this.scrollToBottom());
      } else if (evt.type === 'result') {
        this._handleResult(evt.data);
      } else if (evt.type === 'error') {
        this.messages.push({ role: 'assistant', content: evt.message || 'Error' });
        this.$nextTick(() => this.scrollToBottom());
      }
    },

    _handleResult(result) {
      if (!result) return;

      if (result.task === 'estimate_budget') {
        const totals = result.totals || {};
        const text = `Budget: Hotels €${(totals.hotels || 0).toFixed(2)} · Activities €${(totals.activities || 0).toFixed(2)} · General €${(totals.general_items || 0).toFixed(2)} · Total €${(totals.grand_total || 0).toFixed(2)}`;
        this.messages.push({ role: 'assistant', content: text });
      } else if (result.task === 'summarize_trip') {
        this.messages.push({ role: 'assistant', content: result.summary || 'No summary.' });
      } else {
        // Activities or hotels
        const candidates = result.candidates || [];
        const taskLabel = result.task === 'propose_hotels' ? 'Hotels' : 'Activities';
        const header = `${taskLabel} for ${result.day || '?'} in ${result.location || '?'} (${candidates.length})`;
        this.messages.push({ role: 'assistant', content: header });

        // Render each candidate as a separate message with apply button
        for (const c of candidates) {
          const desc = c.summary || c.details || c.description || '';
          const price = c.price_per_night ?? c.price ?? '';
          let text = `${c.name || 'Option'}`;
          if (c.location) text += ` — ${c.location}`;
          if (desc) text += `\n${desc}`;
          if (price) text += `\n€${price}`;
          this.messages.push({
            role: 'assistant',
            content: text,
            candidates: true,
            _candidate: c,
            _result: result,
          });
        }
      }
      this.$nextTick(() => this.scrollToBottom());
    },

    async applyCandidate(msg) {
      const result = msg._result;
      const candidate = msg._candidate;
      if (!result || !result.day) return;

      const isHotel = result.task === 'propose_hotels';
      const url = isHotel ? '/apply/hotel' : '/apply/activity';
      const payload = {
        trip_id: this.tripId,
        day: result.day,
      };

      if (isHotel) {
        payload.hotel = {
          name: candidate.name || null,
          location: candidate.location || result.location || null,
          description: candidate.description || candidate.details || candidate.summary || '',
          price: candidate.price ?? candidate.price_per_night ?? null,
          reservation_id: candidate.reservation_id || null,
          link: candidate.link || null,
          maps_link: candidate.maps_link || null,
          cancelable: candidate.cancelable ?? null,
        };
      } else {
        payload.activity = {
          name: candidate.name || 'Activity',
          location: candidate.location || result.location || null,
          description: candidate.details || candidate.summary || candidate.description || '',
          price: candidate.price ?? null,
          reservation_id: candidate.reservation_id ?? null,
          link: candidate.link || null,
          maps_link: candidate.maps_link || null,
        };
      }

      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error('Failed to apply');
        const label = isHotel ? 'Hotel saved' : 'Activity added';
        this.messages.push({ role: 'assistant', content: `${label} for ${result.day}.` });

        // Refresh relevant section via HTMX
        if (this.dayId) {
          const target = isHotel ? '#hotel-section' : '#activities-section';
          const partialUrl = isHotel
            ? `/partials/days/${this.dayId}/hotel`
            : `/partials/days/${this.dayId}/activities`;
          htmx.ajax('GET', partialUrl, { target, swap: 'innerHTML' });
        }
      } catch (err) {
        this.messages.push({ role: 'assistant', content: err.message });
      }
      this.$nextTick(() => this.scrollToBottom());
    },

    cancelRequest() {
      if (this._controller) this._controller.abort();
    },

    async clearHistory() {
      let url = `/agent/history/${this.tripId}`;
      if (this.dayId) url += `?day_id=${this.dayId}`;
      await fetch(url, { method: 'DELETE' });
      this.messages = [];
    },

    scrollToBottom() {
      const log = this.$refs.chatLog;
      if (log) log.scrollTop = log.scrollHeight;
    },
  }));

  /* ── One-shot Generation Panel ── */
  Alpine.data('oneshotPanel', (tripId) => ({
    tripId,
    streaming: false,
    streamOutput: '',
    generatedJson: '',
    pasteJson: '',
    pasteError: '',
    previewHtml: '',
    showPreview: false,
    showApply: false,
    promptText: '',
    promptCopied: false,
    taglinesRunning: false,
    taglinesStatus: '',

    /* Generate prompt only (no AI call) */
    async generatePrompt() {
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = `/trips/${this.tripId}/generate-ai`;
      form.setAttribute('hx-disable', '');
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'generate_only';
      input.value = 'true';
      form.appendChild(input);
      document.body.appendChild(form);
      form.submit();
    },

    /* Copy prompt to clipboard */
    async copyPrompt() {
      const el = this.$refs.promptArea;
      if (!el) return;
      try {
        await navigator.clipboard.writeText(el.value || el.textContent || '');
        this.promptCopied = true;
        setTimeout(() => this.promptCopied = false, 1500);
      } catch (e) {
        alert('Could not copy.');
      }
    },

    /* Stream AI generation */
    async generateStream() {
      if (!confirm('Start AI generation? This might take a minute.')) return;
      this.streaming = true;
      this.streamOutput = 'Connecting to AI model...\n';
      this.generatedJson = '';
      this.showPreview = false;
      this.showApply = false;
      let fullText = '';

      try {
        const resp = await fetch(`/api/trips/${this.tripId}/generate_stream`, {
          method: 'POST',
        });
        if (!resp.ok) {
          this.streamOutput += `Error: ${resp.status} ${resp.statusText}`;
          this.streaming = false;
          return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop();

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const dataStr = line.slice(6).trim();
            if (dataStr === '[DONE]') {
              this.streamOutput += '\n[Generation Complete]';
              const jsonMatch = fullText.match(/\{[\s\S]*\}/);
              if (jsonMatch) {
                this.generatedJson = jsonMatch[0];
                this._buildPreview(this.generatedJson);
                this.showApply = true;
              } else {
                this.streamOutput += '\nCould not extract JSON from output.';
              }
              this.streaming = false;
              return;
            }
            try {
              const data = JSON.parse(dataStr);
              if (data.error) {
                this.streamOutput += `\n[Error]: ${data.error}`;
              } else if (data.chunk) {
                this.streamOutput += data.chunk;
                fullText += data.chunk;
              }
            } catch (e) { /* ignore */ }
          }
        }
      } catch (err) {
        this.streamOutput += `\nNetwork error: ${err}`;
      }
      this.streaming = false;
    },

    /* Generate and save taglines for all days */
    async generateTaglines() {
      if (!confirm('Generate a summary tagline for every day? Existing taglines will be replaced.')) return;
      this.taglinesRunning = true;
      this.taglinesStatus = 'Starting...';
      try {
        const resp = await fetch(`/api/trips/${this.tripId}/generate-taglines`, { method: 'POST' });
        if (!resp.ok) {
          this.taglinesStatus = 'Request failed.';
          this.taglinesRunning = false;
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          buffer = parts.pop();
          for (const part of parts) {
            if (!part.startsWith('data: ')) continue;
            try {
              const evt = JSON.parse(part.slice(6).trim());
              if (evt.type === 'progress') {
                const label = evt.tagline ? `"${evt.tagline}"` : 'skipped';
                this.taglinesStatus = `${evt.n}/${evt.total} — ${evt.date}: ${label}`;
              } else if (evt.type === 'done') {
                this.taglinesStatus = `Done — ${evt.updated} day${evt.updated !== 1 ? 's' : ''} updated. Reloading...`;
                setTimeout(() => window.location.reload(), 900);
              } else if (evt.type === 'error') {
                this.taglinesStatus = `Error: ${evt.message}`;
              }
            } catch (e) { /* ignore */ }
          }
        }
      } catch (err) {
        this.taglinesStatus = `Error: ${err.message}`;
      } finally {
        this.taglinesRunning = false;
      }
    },

    /* Apply the generated/pasted JSON via form POST */
    applyJson(jsonStr) {
      if (!confirm('Apply this JSON? This will replace the current trip contents.')) return;
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = `/trips/${this.tripId}/apply-ai-response`;
      form.setAttribute('hx-disable', '');
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'ai_response_text';
      input.value = jsonStr;
      form.appendChild(input);
      document.body.appendChild(form);
      form.submit();
    },

    /* Preview pasted JSON */
    previewPaste() {
      this.pasteError = '';
      this.showPreview = false;
      this.showApply = false;
      const raw = this.pasteJson.trim();
      if (!raw) {
        this.pasteError = 'Paste a JSON first.';
        return;
      }
      try {
        const data = JSON.parse(raw);
        if (!data.days || !data.days.length) {
          this.pasteError = 'Expected {"days": [...], ...}';
          return;
        }
        this._buildPreview(raw);
        this.generatedJson = raw;
        this.showApply = true;
      } catch (e) {
        this.pasteError = 'Invalid JSON: ' + e.message;
      }
    },

    _buildPreview(jsonStr) {
      try {
        const data = JSON.parse(jsonStr);
        const days = data.days || [];
        const general = data.general_items || [];
        const totalAct = days.reduce((s, d) => s + (d.activities || []).length, 0);
        let html = `<div class="text-xs space-y-1">`;
        html += `<div class="font-semibold">${days.length} days, ${totalAct} activities`;
        if (general.length) html += `, ${general.length} general items`;
        html += `</div>`;
        for (const day of days) {
          const hotel = day.hotel;
          const acts = day.activities || [];
          html += `<div class="border-l-2 border-blue-800 pl-2 mt-1">`;
          html += `<span class="font-medium">${day.date || '?'}</span>`;
          if (hotel && hotel.name) html += ` — ${hotel.name}`;
          if (acts.length) {
            html += `<div class="text-slate-400">${acts.map(a => a.name || '?').join(', ')}</div>`;
          }
          html += `</div>`;
        }
        html += `</div>`;
        this.previewHtml = html;
        this.showPreview = true;
      } catch (e) {
        this.previewHtml = '';
        this.showPreview = false;
      }
    },
  }));

});

/* ── Maps itinerary links (carried over from old base.html) ── */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-itinerary-maps]').forEach((trigger) => {
    trigger.addEventListener('click', async (event) => {
      event.preventDefault();
      const url = trigger.getAttribute('data-itinerary-maps');
      if (!url || trigger.dataset.loading === 'true') return;
      trigger.dataset.loading = 'true';
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed');
        const data = await response.json();
        if (data && data.url) {
          window.open(data.url, '_blank');
        } else {
          alert(data?.error || 'Not enough hotel data.');
        }
      } catch (error) {
        alert(error.message || 'Unable to build itinerary.');
      } finally {
        delete trigger.dataset.loading;
      }
    });
  });
});
