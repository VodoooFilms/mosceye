/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#define _DARWIN_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#include "retail_voice.h"
#include <SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/stat.h>

#define NAVY 0x102f73
#define WHITE 0xfffdf9
#define MUTED 0xa9b8ca
#define RATE 16000
#define MAX_SECONDS 30
#define CAPACITY (RATE * 2 * MAX_SECONDS)

typedef enum { IDLE, RECORDING, REVIEW, PLAYING, SHARED } voice_state_t;
static voice_state_t state;
static lv_obj_t *panel, *caption, *clock_label, *note, *record_button;
static lv_obj_t *listen_button, *repeat_button, *share_button, *listen_label;
static lv_obj_t *bars[21];
static SDL_AudioDeviceID capture_device, playback_device;
static uint8_t *samples;
static uint32_t length;
static unsigned level;
static char draft_dir[1024], wav_path[1100];
static bool record_pointer_down;

static lv_obj_t *text(lv_obj_t *parent, const lv_font_t *font, unsigned color, const char *value)
{
    lv_obj_t *o = lv_label_create(parent);
    lv_obj_set_style_text_font(o, font, 0);
    lv_obj_set_style_text_color(o, lv_color_hex(color), 0);
    lv_label_set_text(o, value);
    return o;
}

static void capture(void *unused, Uint8 *stream, int bytes)
{
    (void)unused;
    if (bytes <= 0 || length >= CAPACITY) return;
    uint32_t n = (uint32_t)bytes;
    if (n > CAPACITY - length) n = CAPACITY - length;
    n &= ~1u;
    memcpy(samples + length, stream, n);
    length += n;
    unsigned peak = 0;
    for (uint32_t i = 0; i + 1 < n; i += 2) {
        int v = (int16_t)((unsigned)stream[i] | ((unsigned)stream[i + 1] << 8));
        unsigned magnitude = (unsigned)abs(v);
        if (magnitude > peak) peak = magnitude;
    }
    level = peak;
}

static void stop_playback(void)
{
    if (playback_device) { SDL_CloseAudioDevice(playback_device); playback_device = 0; }
    if (state == PLAYING) state = REVIEW;
}

static void remove_draft(void)
{
    if (wav_path[0]) unlink(wav_path);
    if (draft_dir[0]) rmdir(draft_dir);
    wav_path[0] = draft_dir[0] = 0;
}

static void controls(void)
{
    bool review = state == REVIEW || state == PLAYING;
    if (state == IDLE || state == RECORDING) lv_obj_remove_flag(record_button, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(record_button, LV_OBJ_FLAG_HIDDEN);
    lv_obj_t *buttons[] = { listen_button, repeat_button, share_button };
    for (unsigned i = 0; i < 3; i++) {
        if (review) lv_obj_remove_flag(buttons[i], LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(buttons[i], LV_OBJ_FLAG_HIDDEN);
    }
    lv_label_set_text(listen_label, state == PLAYING ? "DETENER" : "ESCUCHAR");
    lv_label_set_text(caption, state == RECORDING ? "Grabando tu mensaje" :
                     review ? "Tu mensaje esta listo" : state == SHARED ? "Continua en WhatsApp" : "Mensaje de voz");
}

static bool audio_init(void)
{
    if (!(SDL_WasInit(SDL_INIT_AUDIO) & SDL_INIT_AUDIO) && SDL_InitSubSystem(SDL_INIT_AUDIO) < 0) {
        lv_label_set_text(note, "No se pudo iniciar el audio.");
        return false;
    }
    if (!samples) samples = SDL_malloc(CAPACITY);
    if (!samples) { lv_label_set_text(note, "No hay memoria para grabar."); return false; }
    return true;
}

static void start_recording(void)
{
    if (state != IDLE) return;
#ifdef __APPLE__
    const char *driver = getenv("SDL_AUDIODRIVER");
    if (!driver || strcmp(driver, "dummy")) {
        int permission = retail_voice_microphone_permission();
        if (permission != 1) {
            lv_label_set_text(note, permission == 0 ? "Autoriza el microfono y vuelve a grabar." :
                              "Activa el microfono en Privacidad de macOS.");
            return;
        }
    }
#endif
    if (!audio_init()) return;
    SDL_AudioSpec desired = {0};
    desired.freq = RATE; desired.format = AUDIO_S16LSB; desired.channels = 1;
    desired.samples = 512; desired.callback = capture;
    capture_device = SDL_OpenAudioDevice(NULL, 1, &desired, NULL, 0);
    if (!capture_device) { lv_label_set_text(note, "No se pudo abrir el microfono. Reintenta."); return; }
    length = 0; level = 0;
    state = RECORDING;
    lv_label_set_text(note, "Suelta para terminar. Maximo 30 segundos.");
    controls();
    SDL_PauseAudioDevice(capture_device, 0);
}

static void le32(uint8_t *p, uint32_t value)
{
    for (int i = 0; i < 4; i++) p[i] = (uint8_t)(value >> (8 * i));
}

static bool write_wav(void)
{
    remove_draft();
    const char *temporary = getenv("TMPDIR");
    int n = snprintf(draft_dir, sizeof(draft_dir), "%s/mosceye-voice-XXXXXX",
                     temporary && temporary[0] ? temporary : "/tmp");
    if (n < 0 || (size_t)n >= sizeof(draft_dir)) { draft_dir[0] = 0; return false; }
    if (!mkdtemp(draft_dir)) { draft_dir[0] = 0; return false; }
    snprintf(wav_path, sizeof(wav_path), "%s/draft.wav", draft_dir);
    FILE *f = fopen(wav_path, "wb");
    if (!f) { remove_draft(); return false; }
    uint8_t header[44] = {0};
    memcpy(header, "RIFF", 4); le32(header + 4, 36 + length);
    memcpy(header + 8, "WAVEfmt ", 8); le32(header + 16, 16);
    header[20] = 1; header[22] = 1; le32(header + 24, RATE);
    le32(header + 28, RATE * 2); header[32] = 2; header[34] = 16;
    memcpy(header + 36, "data", 4); le32(header + 40, length);
    bool ok = fwrite(header, 1, sizeof(header), f) == sizeof(header);
    ok = (fwrite(samples, 1, length, f) == length) && ok;
    if (fclose(f)) ok = false;
    if (ok) chmod(wav_path, 0600);
    else remove_draft();
    return ok;
}

static void finish_recording(void)
{
    if (state != RECORDING) return;
    SDL_CloseAudioDevice(capture_device); capture_device = 0;
    if (length < RATE * 2 / 2) {
        state = IDLE;
        lv_label_set_text(note, "Muy corto. Manten pulsado al menos medio segundo.");
    } else if (!write_wav()) {
        state = IDLE;
        lv_label_set_text(note, "No se pudo guardar el audio. Vuelve a grabar.");
    } else {
        state = REVIEW;
        lv_label_set_text(note, "Escuchalo antes de compartirlo.");
    }
    controls();
}

static void listen(void)
{
    if (state == PLAYING) { stop_playback(); controls(); return; }
    if (state != REVIEW || !length) return;
    SDL_AudioSpec desired = {0};
    desired.freq = RATE; desired.format = AUDIO_S16LSB; desired.channels = 1;
    desired.samples = 512;
    playback_device = SDL_OpenAudioDevice(NULL, 0, &desired, NULL, 0);
    if (!playback_device || SDL_QueueAudio(playback_device, samples, length)) {
        stop_playback();
        lv_label_set_text(note, "No se pudo reproducir. Revisa la salida de audio.");
        return;
    }
    state = PLAYING;
    SDL_PauseAudioDevice(playback_device, 0);
    controls();
}

static void repeat(void)
{
    if (state != REVIEW && state != PLAYING) return;
    stop_playback(); remove_draft(); length = level = 0;
    state = IDLE;
    lv_label_set_text(note, "Manten pulsado para grabar. Suelta al terminar.");
    controls();
}

static void share(void)
{
    if (state != REVIEW && state != PLAYING) return;
    stop_playback();
    char error[180] = "Compartir audio requiere la app de macOS.";
#ifdef __APPLE__
    if (retail_voice_share_mac(wav_path, error, sizeof(error))) {
        state = SHARED;
        lv_label_set_text(note, "Audio copiado. Elige el chat y pegalo.\nEnvialo desde WhatsApp.");
        controls();
        return;
    }
#endif
    lv_label_set_text(note, error);
    controls();
}

static void close_panel(void)
{
    record_pointer_down = false;
    if (capture_device) { SDL_CloseAudioDevice(capture_device); capture_device = 0; }
    stop_playback(); remove_draft(); length = level = 0; state = IDLE;
    lv_obj_add_flag(panel, LV_OBJ_FLAG_HIDDEN);
}

static void event_cb(lv_event_t *e)
{
    const char *command = lv_event_get_user_data(e);
    if (!strcmp(command, "record")) {
        if (lv_event_get_code(e) == LV_EVENT_PRESSED) start_recording();
        else if (lv_event_get_code(e) == LV_EVENT_RELEASED || lv_event_get_code(e) == LV_EVENT_PRESS_LOST)
            finish_recording();
    } else if (lv_event_get_code(e) == LV_EVENT_CLICKED) retail_voice_command(command);
}

static lv_obj_t *button(const char *value, int x, int y, int w, const char *command)
{
    lv_obj_t *o = lv_button_create(panel);
    lv_obj_set_pos(o, x, y); lv_obj_set_size(o, w, 44);
    lv_obj_set_style_bg_opa(o, LV_OPA_TRANSP, 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_TRANSP, LV_STATE_PRESSED);
    lv_obj_set_style_shadow_width(o, 0, 0);
    lv_obj_set_style_border_width(o, 0, 0);
    lv_obj_set_style_pad_all(o, 0, 0);
    lv_obj_set_style_opa(o, LV_OPA_70, LV_STATE_PRESSED);
    lv_obj_t *t = text(o, &lv_font_montserrat_14, WHITE, value);
    lv_obj_set_style_text_letter_space(t, 1, 0);
    lv_obj_set_style_text_decor(t, LV_TEXT_DECOR_UNDERLINE, 0);
    lv_obj_center(t);
    lv_obj_add_event_cb(o, event_cb, LV_EVENT_ALL, (void *)command);
    return o;
}

static void tick(lv_timer_t *timer)
{
    (void)timer;
    if (!retail_voice_visible()) return;
    uint32_t bytes;
    unsigned peak;
    if (capture_device) {
        SDL_LockAudioDevice(capture_device);
        bytes = length; peak = level;
        SDL_UnlockAudioDevice(capture_device);
    } else { bytes = length; peak = level; }
    if (state == RECORDING && bytes >= CAPACITY) finish_recording();
    if (state == PLAYING && !SDL_GetQueuedAudioSize(playback_device)) { stop_playback(); controls(); }
    unsigned seconds = bytes / (RATE * 2);
    lv_label_set_text_fmt(clock_label, "%02u:%02u", seconds / 60, seconds % 60);
    for (int i = 0; i < 21; i++) {
        unsigned magnitude = 0;
        if (state == RECORDING) magnitude = peak * (unsigned)(4 + ((i * 7) % 9)) / 12;
        else if (bytes && samples) {
            uint32_t start = ((bytes / 2) * (unsigned)i / 21) * 2;
            uint32_t end = ((bytes / 2) * (unsigned)(i + 1) / 21) * 2;
            for (uint32_t j = start; j + 1 < end; j += 64) {
                int v = (int16_t)((unsigned)samples[j] | ((unsigned)samples[j + 1] << 8));
                unsigned n = (unsigned)abs(v);
                if (n > magnitude) magnitude = n;
            }
        }
        int height = 4 + (int)(magnitude * 56 / 32768);
        lv_obj_set_height(bars[i], height);
        lv_obj_set_y(bars[i], 185 - height / 2);
    }
}

void retail_voice_init(lv_obj_t *parent)
{
    panel = lv_obj_create(parent);
    lv_obj_set_size(panel, 412, 412); lv_obj_set_pos(panel, 0, 0);
    lv_obj_set_style_bg_color(panel, lv_color_hex(NAVY), 0);
    lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(panel, 0, 0);
    lv_obj_set_style_radius(panel, 0, 0); lv_obj_set_style_pad_all(panel, 0, 0);
    lv_obj_remove_flag(panel, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *brand = text(panel, &lv_font_montserrat_16, MUTED, "MOSCEYE");
    lv_obj_set_style_text_letter_space(brand, 4, 0); lv_obj_set_pos(brand, 27, 25);
    button("Volver", 306, 12, 85, "close");
    lv_obj_t *target = text(panel, &lv_font_montserrat_14, MUTED, "Para el cajero / WhatsApp");
    lv_obj_align(target, LV_ALIGN_TOP_MID, 0, 73);
    caption = text(panel, &lv_font_montserrat_20, WHITE, "Mensaje de voz");
    lv_obj_align(caption, LV_ALIGN_TOP_MID, 0, 108);
    for (int i = 0; i < 21; i++) {
        bars[i] = lv_obj_create(panel);
        lv_obj_set_size(bars[i], 4, 4); lv_obj_set_pos(bars[i], 103 + i * 10, 183);
        lv_obj_set_style_bg_color(bars[i], lv_color_hex(WHITE), 0);
        lv_obj_set_style_bg_opa(bars[i], LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(bars[i], 0, 0); lv_obj_set_style_radius(bars[i], 2, 0);
        lv_obj_remove_flag(bars[i], LV_OBJ_FLAG_SCROLLABLE);
    }
    clock_label = text(panel, &lv_font_montserrat_28, WHITE, "00:00");
    lv_obj_align(clock_label, LV_ALIGN_TOP_MID, 0, 224);
    record_button = button("MANTEN PARA GRABAR", 47, 282, 318, "record");
    listen_button = button("ESCUCHAR", 55, 273, 145, "listen");
    listen_label = lv_obj_get_child(listen_button, 0);
    repeat_button = button("REPETIR", 217, 273, 140, "repeat");
    share_button = button("ABRIR WHATSAPP", 47, 319, 318, "share");
    note = text(panel, &lv_font_montserrat_14, MUTED, "");
    lv_obj_set_width(note, 358); lv_obj_set_style_text_align(note, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(note, LV_ALIGN_BOTTOM_MID, 0, -15);
    controls();
    lv_obj_add_flag(panel, LV_OBJ_FLAG_HIDDEN);
    lv_timer_create(tick, 80, NULL);
}

void retail_voice_open(void)
{
    if (!panel || retail_voice_visible()) return;
    state = IDLE; length = level = 0;
    lv_label_set_text(note, "Manten pulsado para grabar.\nSuelta al terminar.");
    lv_obj_remove_flag(panel, LV_OBJ_FLAG_HIDDEN); lv_obj_move_foreground(panel);
    controls(); tick(NULL);
}

bool retail_voice_visible(void) { return panel && !lv_obj_has_flag(panel, LV_OBJ_FLAG_HIDDEN); }

void retail_voice_pointer_event(int x, int y, bool pressed)
{
    if (!retail_voice_visible()) return;
    if (!pressed || x < 0 || y < 0) {
        if (record_pointer_down) finish_recording();
        record_pointer_down = false;
    } else if (state == IDLE && x >= 47 && x < 365 && y >= 282 && y < 326) {
        record_pointer_down = true;
        start_recording();
    }
}

void retail_voice_cleanup(void)
{
    if (panel) close_panel();
    SDL_free(samples); samples = NULL;
    if (SDL_WasInit(SDL_INIT_AUDIO) & SDL_INIT_AUDIO) SDL_QuitSubSystem(SDL_INIT_AUDIO);
}

bool retail_voice_command(const char *command)
{
    if (!strcmp(command, "open")) retail_voice_open();
    else if (!retail_voice_visible()) return false;
    else if (!strcmp(command, "close")) close_panel();
    else if (!strcmp(command, "record")) start_recording();
    else if (!strcmp(command, "stop")) finish_recording();
    else if (!strcmp(command, "listen")) listen();
    else if (!strcmp(command, "repeat")) repeat();
    else if (!strcmp(command, "share")) share();
    else return false;
    return true;
}
