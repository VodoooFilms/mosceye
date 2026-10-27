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

#include "retail_view.h"
#include "retail_voice.h"
#include "lvgl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <stdint.h>

LV_FONT_DECLARE(retail_number_176)
LV_IMAGE_DECLARE(mosceye_logo);

#define STATUS_PATH "/tmp/caja_status.json"
#define ACK_PATH "/tmp/mosceye_trigger_ack.json"
#define SIGNAL_PATH "/tmp/mosceye_trigger.json"
#define ORANGE 0xc75a23
#define WHITE 0xfffdf9
#define NAVY 0x102f73
#define SECONDARY 0xa9b8ca

typedef struct {
    lv_obj_t *root, *number, *placeholder, *other_number, *staff, *cashier, *cashier_text;
    lv_obj_t *title_row, *other_title;
} metric_page_t;
static metric_page_t s_pages[2];
static lv_obj_t *s_root, *s_pager, *s_welcome, *s_timestamp, *s_status, *s_brand;
static lv_obj_t *s_button, *s_button_label, *s_dots[2];
static bool s_checking, s_store_page, s_server_busy, s_started;
static bool s_drag_active, s_drag_moved;
static int s_drag_x, s_drag_y, s_drag_offset, s_drag_page;
static char s_local_error[256];
static uint32_t s_check_started;
static char s_pending_client[81], s_pending_request[81];
static char s_entry_request[81];
static void refresh(void);

/* Small flat contract parser. Values originate from MOSCEYE's JSON serializer. */
static const char *value_at(const char *json, const char *key)
{
    char needle[100];
    snprintf(needle, sizeof(needle), "\"%s\"", key);
    const char *p = strstr(json, needle);
    if (!p) return NULL;
    p += strlen(needle);
    while (*p == ' ' || *p == '\t') p++;
    if (*p++ != ':') return NULL;
    while (*p == ' ' || *p == '\t') p++;
    return p;
}

static bool get_string(const char *json, const char *key, char *out, size_t size)
{
    const char *p = value_at(json, key);
    if (!p || *p++ != '"') { if (size) out[0] = 0; return false; }
    size_t i = 0;
    while (*p && *p != '"') {
        if (*p == '\\' && p[1]) p++;
        if (i + 1 < size) out[i++] = *p;
        p++;
    }
    out[i] = 0;
    return *p == '"';
}

static bool get_number(const char *json, const char *key, double *out)
{
    const char *p = value_at(json, key);
    if (!p) return false;
    char *end;
    double n = strtod(p, &end);
    if (end == p) return false;
    *out = n;
    return true;
}

static bool get_bool(const char *json, const char *key)
{
    const char *p = value_at(json, key);
    return p && !strncmp(p, "true", 4);
}

static bool read_json(const char *path, char *buf, size_t size)
{
    FILE *f = fopen(path, "r");
    if (!f) return false;
    size_t n = fread(buf, 1, size - 1, f);
    fclose(f);
    buf[n] = 0;
    return n > 1 && buf[0] == '{';
}

static lv_obj_t *label(lv_obj_t *parent, const lv_font_t *font, unsigned color, const char *text)
{
    lv_obj_t *o = lv_label_create(parent);
    lv_obj_set_style_text_font(o, font, 0);
    lv_obj_set_style_text_color(o, lv_color_hex(color), 0);
    lv_label_set_text(o, text);
    return o;
}

static void set_busy(bool busy)
{
    s_checking = busy;
    lv_label_set_text(s_button_label, busy ? "CHEQUEANDO..." : "CHEQUEAR");
    if (busy) lv_obj_add_state(s_button, LV_STATE_DISABLED);
    else lv_obj_remove_state(s_button, LV_STATE_DISABLED);
}

static void number_text(lv_obj_t *object, bool valid, int count)
{
    char text[12];
    if (!valid) { lv_label_set_text(object, ""); return; }
    snprintf(text, sizeof(text), count > 99 ? "99+" : "%d", count);
    lv_label_set_text(object, text);
}

static void cashier_icon(metric_page_t *page, bool known, bool present)
{
    lv_obj_set_style_bg_opa(page->cashier, known && present ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
    lv_obj_set_style_bg_color(page->cashier, lv_color_hex(ORANGE), 0);
    lv_obj_set_style_border_color(page->cashier, lv_color_hex(known ? ORANGE : SECONDARY), 0);
    lv_obj_set_style_text_color(page->cashier_text,
        lv_color_hex(!known ? SECONDARY : present ? WHITE : ORANGE), 0);
    lv_label_set_text(page->staff, !known ? "CAJA SIN DATOS" : present ? "CAJA ATENDIDA" : "CAJA SIN ATENDER");
}

static void show_numbers(bool good, bool q_valid, int queue, bool st_valid, int store,
                         bool connected, bool cashier_known, bool cashier_present, bool loading)
{
    for (int i = 0; i < 2; i++) {
        metric_page_t *page = &s_pages[i];
        bool valid = good && (i ? st_valid : q_valid);
        number_text(page->number, valid, i ? store : queue);
        lv_obj_set_style_text_color(page->number, lv_color_hex(connected ? WHITE : SECONDARY), 0);
        lv_label_set_text(page->placeholder, loading ? "Consultando..." : i || q_valid ? "Sin datos" : "Configura las zonas");
        if (valid) lv_obj_add_flag(page->placeholder, LV_OBJ_FLAG_HIDDEN);
        else lv_obj_remove_flag(page->placeholder, LV_OBJ_FLAG_HIDDEN);
        if (good && (i ? q_valid : st_valid))
            lv_label_set_text_fmt(page->other_number, "%d", i ? queue : store);
        else lv_label_set_text(page->other_number, "--");
        cashier_icon(page, good && cashier_known, cashier_present);
    }
}

static void dim_readout(bool previous_or_missing)
{
    lv_opa_t opacity = previous_or_missing ? LV_OPA_50 : LV_OPA_COVER;
    for (int i = 0; i < 2; i++) {
        metric_page_t *page = &s_pages[i];
        lv_obj_t *information[] = { page->number, page->placeholder, page->title_row,
                                   page->other_number, page->other_title, page->staff };
        for (unsigned j = 0; j < sizeof(information) / sizeof(information[0]); j++)
            lv_obj_set_style_opa(information[j], opacity, 0);
    }
    lv_obj_set_style_opa(s_brand, opacity, 0);
    lv_obj_set_style_opa(s_timestamp, opacity, 0);
    lv_obj_set_style_opa(s_status, opacity, 0);
}

static void refresh(void)
{
    if (!s_root) return;
    char buf[4096], ack[1024], request[81], client[81], phase[24], error[256];
    double queue = 0, store = 0, captured = 0, published = 0;
    const char *status_path = getenv("MOSCEYE_STATUS_PATH");
    bool available = read_json(status_path ? status_path : STATUS_PATH, buf, sizeof(buf));
    if (!available) {
        s_server_busy = false;
        dim_readout(true);
        show_numbers(false, false, 0, false, 0, false, false, false, false);
        lv_label_set_text(s_status, "SERVIDOR SIN CONEXION");
        lv_label_set_text(s_timestamp, "Abre MOSCEYE Desktop");
        if (s_checking && lv_tick_get() - s_check_started > 15000) set_busy(false);
        return;
    }
    get_string(buf, "request_id", request, sizeof(request));
    get_string(buf, "client_request_id", client, sizeof(client));
    get_string(buf, "phase", phase, sizeof(phase));
    get_string(buf, "error", error, sizeof(error));
    get_number(buf, "published_epoch", &published);
    bool connected = published > 0 && difftime(time(NULL), (time_t)published) < 5;
    bool good = get_bool(buf, "counts_ready") && !error[0];
    s_server_busy = connected && get_bool(buf, "busy");
    bool q_valid = get_number(buf, "people_in_queue", &queue) && queue >= 0;
    bool st_valid = get_number(buf, "people_in_store", &store) && store >= 0;
    get_number(buf, "captured_epoch", &captured);

    if (s_checking && read_json(ACK_PATH, ack, sizeof(ack))) {
        char ack_client[81], ack_error[256];
        get_string(ack, "client_request_id", ack_client, sizeof(ack_client));
        if (!strcmp(ack_client, s_pending_client)) {
            get_string(ack, "error", ack_error, sizeof(ack_error));
            if (ack_error[0]) {
                set_busy(false);
                snprintf(s_local_error, sizeof(s_local_error), "%s", ack_error);
                lv_label_set_text(s_status, ack_error);
                return;
            }
            get_string(ack, "request_id", s_pending_request, sizeof(s_pending_request));
        }
    }
    bool our_request = !strcmp(client, s_pending_client) ||
                       (s_pending_request[0] && !strcmp(request, s_pending_request));
    if (s_checking && our_request && (good || !strcmp(phase, "error"))) {
        set_busy(false);
    }
    if (s_checking && lv_tick_get() - s_check_started > 15000) {
        set_busy(false);
        snprintf(s_local_error, sizeof(s_local_error), "SIN RESPUESTA. REINTENTA.");
        lv_label_set_text(s_status, s_local_error);
        return;
    }
    if (s_checking) {
        dim_readout(true);
        show_numbers(false, q_valid, 0, st_valid, 0, connected, false, false, true);
        lv_label_set_text(s_status, "Consultando la camara...");
        return;
    }
    show_numbers(good, q_valid, (int)queue, st_valid, (int)store, connected,
                 connected && get_bool(buf, "zones_calibrated"), get_bool(buf, "cashier_present"),
                 get_bool(buf, "checking"));
    bool previous = good && (!connected || !strcmp(request, s_entry_request));
    dim_readout(previous || !good);
    if (good && captured > 0) {
        time_t when = (time_t)captured;
        struct tm tm;
        char text[80], hm[16];
        localtime_r(&when, &tm);
        strftime(hm, sizeof(hm), "%H:%M:%S", &tm);
        long age = (long)difftime(time(NULL), when);
        if (age < 0) age = 0;
        if (age < 60) snprintf(text, sizeof(text), "%s  /  hace %ld s", hm, age);
        else snprintf(text, sizeof(text), "%s  /  hace %ld min", hm, age / 60);
        lv_label_set_text(s_timestamp, text);
    } else lv_label_set_text(s_timestamp, "Sin un conteo disponible");
    if (!connected) lv_label_set_text(s_status, "SIN CONEXION / ULTIMO DATO");
    else if (error[0]) lv_label_set_text(s_status, error);
    else if (get_bool(buf, "checking")) lv_label_set_text(s_status, "Chequeo desde Desktop en curso...");
    else if (previous) lv_label_set_text(s_status, "DATO ANTERIOR / Pulsa CHEQUEAR.");
    else if (good) lv_label_set_text(s_status, s_store_page ? "Incluye clientes y personal." : "Desliza para ver la tienda.");
    else lv_label_set_text(s_status, "Pulsa CHEQUEAR para consultar.");
    /* A recovered server must clear the previous timeout instead of pinning it forever. */
    if (s_local_error[0] && connected && good && !s_checking) s_local_error[0] = 0;
    if (s_local_error[0]) lv_label_set_text(s_status, s_local_error);
    if (s_server_busy) {
        lv_obj_add_state(s_button, LV_STATE_DISABLED);
        lv_label_set_text(s_button_label, good ? "CHEQUEAR" : "CHEQUEANDO...");
    } else {
        lv_obj_remove_state(s_button, LV_STATE_DISABLED);
        lv_label_set_text(s_button_label, "CHEQUEAR");
    }
}

static bool write_signal(const char *payload)
{
    char path[180];
    snprintf(path, sizeof(path), "%s.%ld.tmp", SIGNAL_PATH, (long)getpid());
    FILE *f = fopen(path, "w");
    if (!f) return false;
    fputs(payload, f);
    fclose(f);
    if (rename(path, SIGNAL_PATH)) { unlink(path); return false; }
    return true;
}

void retail_view_check(void)
{
    if (!s_root || s_checking || s_server_busy) return;
    retail_view_start();
    s_local_error[0] = 0;
    snprintf(s_pending_client, sizeof(s_pending_client), "%ld-%lu-%ld", (long)time(NULL), (unsigned long)lv_tick_get(), (long)getpid());
    s_pending_request[0] = 0;
    char payload[160];
    snprintf(payload, sizeof(payload), "{\"action\":\"check\",\"request_id\":\"%s\"}\n", s_pending_client);
    if (!write_signal(payload)) { lv_label_set_text(s_status, "No se pudo enviar el chequeo."); return; }
    s_check_started = lv_tick_get();
    set_busy(true);
    refresh();
}

static void check_cb(lv_event_t *e) { (void)e; retail_view_check(); }
static void poll_cb(lv_timer_t *t) { (void)t; refresh(); }

static void update_dots(void)
{
    for (int i = 0; i < 2; i++) {
        bool active = i == (s_store_page ? 1 : 0);
        lv_obj_set_width(s_dots[i], active ? 17 : 5);
        lv_obj_set_style_bg_opa(s_dots[i], active ? LV_OPA_COVER : LV_OPA_40, 0);
    }
}

static void page_scroll_cb(lv_event_t *e)
{
    (void)e;
    if (s_drag_active) return;
    s_store_page = lv_obj_get_scroll_x(s_pager) >= 206;
    update_dots();
    refresh();
}

static void dot_cb(lv_event_t *e)
{
    bool store = (intptr_t)lv_event_get_user_data(e) != 0;
    lv_obj_scroll_to_x(s_pager, store ? 412 : 0, LV_ANIM_ON);
}

static void home_cb(lv_event_t *e)
{
    (void)e;
    s_started = false;
    lv_obj_remove_flag(s_welcome, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_welcome);
}
static void start_cb(lv_event_t *e)
{
    (void)e;
    retail_view_start();
    /* EMPEZAR restarts the demo: the server replays the footage from the
     * beginning and clears the previous analysis from every screen. */
    write_signal("{\"action\":\"start\"}\n");
}

static lv_obj_t *box(lv_obj_t *parent, int x, int y, int w, int h, unsigned color)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_set_size(o, w, h);
    lv_obj_set_pos(o, x, y);
    lv_obj_set_style_bg_color(o, lv_color_hex(color), 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(o, 0, 0);
    lv_obj_set_style_radius(o, 0, 0);
    lv_obj_set_style_pad_all(o, 0, 0);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

static lv_obj_t *emblem(lv_obj_t *parent, int x, int y, int scale)
{
    lv_obj_t *o = lv_image_create(parent);
    lv_image_set_src(o, &mosceye_logo);
    lv_obj_set_style_image_recolor(o, lv_color_hex(WHITE), 0);
    lv_obj_set_style_image_recolor_opa(o, LV_OPA_COVER, 0);
    lv_image_set_scale(o, scale);
    lv_image_set_pivot(o, 0, 0);
    lv_obj_set_pos(o, x, y);
    return o;
}

static lv_obj_t *action(lv_obj_t *parent, const char *text, lv_event_cb_t cb)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_set_size(btn, 358, 43);
    lv_obj_set_pos(btn, 27, 333);
    lv_obj_set_style_bg_opa(btn, LV_OPA_TRANSP, 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_TRANSP, LV_STATE_PRESSED);
    lv_obj_set_style_opa(btn, LV_OPA_70, LV_STATE_PRESSED);
    lv_obj_set_style_radius(btn, 8, 0);
    lv_obj_set_style_shadow_width(btn, 0, 0);
    lv_obj_set_style_border_width(btn, 0, 0);
    lv_obj_add_event_cb(btn, cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *text_label = label(btn, &lv_font_montserrat_16, WHITE, text);
    lv_obj_set_style_text_letter_space(text_label, 2, 0);
    lv_obj_set_style_text_decor(text_label, LV_TEXT_DECOR_UNDERLINE, 0);
    lv_obj_center(text_label);
    return btn;
}

void retail_view_pointer_event(int x, int y, bool pressed)
{
    if (retail_voice_visible()) {
        s_drag_active = false;
        retail_voice_pointer_event(x, y, pressed);
        return;
    }
    if (!retail_view_visible() || !s_started) { s_drag_active = false; return; }
    /* Dragging out of the window reports coordinates outside the display;
     * pin them to the edge so the drag math never leaves the pager range. */
    lv_point_t pt = { .x = x < 0 ? 0 : x > 411 ? 411 : x,
                      .y = y < 0 ? 0 : y > 411 ? 411 : y };
    if (pressed) {
        if (!s_drag_active) {
            if (pt.y < 78 || pt.y >= 313 || pt.x < 0 || pt.x >= 412) return;
            s_drag_active = true;
            s_drag_moved = false;
            s_drag_x = pt.x;
            s_drag_y = pt.y;
            s_drag_offset = lv_obj_get_scroll_x(s_pager);
            s_drag_page = s_store_page ? 1 : 0;
            lv_anim_delete(s_pager, NULL);
        }
        int dx = s_drag_x - (int)pt.x;
        int dy = s_drag_y - (int)pt.y;
        if (!s_drag_moved && abs(dx) > 10 && abs(dx) > abs(dy)) s_drag_moved = true;
        if (s_drag_moved) {
            int offset = s_drag_offset + dx;
            if (offset < 0) offset = 0;
            if (offset > 412) offset = 412;
            lv_obj_scroll_to_x(s_pager, offset, LV_ANIM_OFF);
        }
    } else if (s_drag_active) {
        int moved = lv_obj_get_scroll_x(s_pager) - s_drag_offset;
        int target = s_drag_page;
        if (moved > 60) target = 1;
        if (moved < -60) target = 0;
        s_drag_active = false;
        s_store_page = target != 0;
        update_dots();
        lv_obj_scroll_to_x(s_pager, target * 412, LV_ANIM_ON);
        refresh();
    }
}

static void voice_cb(lv_event_t *e) { (void)e; retail_voice_open(); }

static void make_page(int index)
{
    metric_page_t *page = &s_pages[index];
    page->root = box(s_pager, 0, 0, 412, 235, NAVY);
    lv_obj_add_flag(page->root, LV_OBJ_FLAG_SNAPPABLE);
    page->number = label(page->root, &retail_number_176, WHITE, "");
    lv_obj_align(page->number, LV_ALIGN_TOP_MID, 0, 11);
    page->placeholder = label(page->root, &lv_font_montserrat_20, WHITE, "Sin datos");
    lv_obj_align(page->placeholder, LV_ALIGN_TOP_MID, 0, 63);
    lv_obj_t *title_row = box(page->root, 0, 155, LV_SIZE_CONTENT, 20, NAVY);
    page->title_row = title_row;
    lv_obj_set_flex_flow(title_row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(title_row, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(title_row, 9, 0);
    lv_obj_align(title_row, LV_ALIGN_TOP_MID, 0, 155);
    /* A small native person silhouette; no font glyph dependency. */
    lv_obj_t *person = box(title_row, 0, 0, 14, 18, NAVY);
    lv_obj_t *head = box(person, 4, 0, 6, 6, WHITE);
    lv_obj_set_style_radius(head, LV_RADIUS_CIRCLE, 0);
    lv_obj_t *body = box(person, 1, 8, 12, 10, WHITE);
    lv_obj_set_style_radius(body, 5, 0);
    lv_obj_t *title = label(title_row, &lv_font_montserrat_16, WHITE,
                           index ? "PERSONAS VISIBLES" : "PERSONAS EN FILA");
    lv_obj_set_style_text_letter_space(title, 2, 0);
    lv_obj_t *card = box(page->root, 27, 180, 358, 55, NAVY);
    page->other_number = label(card, &lv_font_montserrat_28, WHITE, "--");
    lv_obj_align(page->other_number, LV_ALIGN_LEFT_MID, 15, 0);
    lv_obj_t *other_title = label(card, &lv_font_montserrat_14, SECONDARY,
                                  index ? "PERSONAS EN FILA" : "PERSONAS VISIBLES");
    page->other_title = other_title;
    lv_obj_set_pos(other_title, 72, 9);
    page->staff = label(card, &lv_font_montserrat_14, SECONDARY, "CAJA SIN DATOS");
    lv_obj_set_pos(page->staff, 72, 30);
    page->cashier = box(card, 313, 14, 27, 27, ORANGE);
    lv_obj_set_style_radius(page->cashier, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(page->cashier, 2, 0);
    lv_obj_set_style_border_color(page->cashier, lv_color_hex(ORANGE), 0);
    page->cashier_text = label(page->cashier, &lv_font_montserrat_14, WHITE, "C");
    lv_obj_center(page->cashier_text);
    cashier_icon(page, false, false);
    /* The C remains a small icon, with a larger transparent touch target. */
    lv_obj_t *voice_hit = box(card, 303, 0, 46, 55, NAVY);
    lv_obj_set_style_bg_opa(voice_hit, LV_OPA_TRANSP, 0);
    lv_obj_add_flag(voice_hit, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(voice_hit, voice_cb, LV_EVENT_CLICKED, NULL);
}

void retail_view_init(void)
{
    if (s_root) return;
    s_root = box(lv_screen_active(), 0, 0, 412, 412, NAVY);
    s_brand = label(s_root, &lv_font_montserrat_16, WHITE, "MOSCEYE");
    lv_obj_set_style_text_letter_space(s_brand, 4, 0);
    lv_obj_set_pos(s_brand, 27, 25);
    lv_obj_t *home = lv_button_create(s_root);
    lv_obj_set_size(home, 75, 42);
    lv_obj_set_pos(home, 314, 13);
    lv_obj_set_style_bg_opa(home, LV_OPA_TRANSP, 0);
    lv_obj_set_style_shadow_width(home, 0, 0);
    lv_obj_set_style_border_width(home, 0, 0);
    lv_obj_add_event_cb(home, home_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *home_text = label(home, &lv_font_montserrat_14, WHITE, "Inicio");
    lv_obj_center(home_text);
    s_timestamp = label(s_root, &lv_font_montserrat_14, SECONDARY, "Sin chequeos todavia");
    lv_obj_set_pos(s_timestamp, 27, 57);

    s_pager = box(s_root, 0, 78, 412, 235, NAVY);
    /* Pointer tracking below provides direct, predictable 1:1 drag. */
    lv_obj_remove_flag(s_pager, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(s_pager, LV_DIR_HOR);
    lv_obj_set_scroll_snap_x(s_pager, LV_SCROLL_SNAP_CENTER);
    lv_obj_set_scrollbar_mode(s_pager, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_flex_flow(s_pager, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(s_pager, 0, 0);
    lv_obj_add_event_cb(s_pager, page_scroll_cb, LV_EVENT_SCROLL_END, NULL);
    make_page(0);
    make_page(1);

    for (int i = 0; i < 2; i++) {
        lv_obj_t *hit = box(s_root, 181 + i * 26, 313, 26, 19, NAVY);
        lv_obj_add_event_cb(hit, dot_cb, LV_EVENT_CLICKED, (void *)(intptr_t)i);
        s_dots[i] = box(hit, 0, 0, 5, 5, WHITE);
        lv_obj_set_style_radius(s_dots[i], LV_RADIUS_CIRCLE, 0);
        lv_obj_align(s_dots[i], LV_ALIGN_CENTER, 0, 0);
        lv_obj_remove_flag(s_dots[i], LV_OBJ_FLAG_CLICKABLE);
    }
    update_dots();
    s_button = action(s_root, "CHEQUEAR", check_cb);
    s_button_label = lv_obj_get_child(s_button, 0);
    /* Keep the full touch target, with typography as the visible action. */
    lv_obj_set_style_bg_opa(s_button, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(s_button, LV_OPA_TRANSP, LV_PART_MAIN | LV_STATE_PRESSED);
    lv_obj_set_style_bg_opa(s_button, LV_OPA_TRANSP, LV_PART_MAIN | LV_STATE_DISABLED);
    lv_obj_set_style_text_color(s_button_label, lv_color_hex(WHITE), 0);
    lv_obj_set_style_text_opa(s_button_label, LV_OPA_50, LV_STATE_DISABLED);
    lv_obj_set_style_opa(s_button, LV_OPA_60, LV_STATE_DISABLED);
    lv_obj_set_style_opa(s_button, LV_OPA_70, LV_STATE_PRESSED);
    s_status = label(s_root, &lv_font_montserrat_14, SECONDARY, "Pulsa CHEQUEAR para consultar.");
    lv_obj_set_size(s_status, 358, 18);
    lv_obj_set_style_text_align(s_status, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_long_mode(s_status, LV_LABEL_LONG_DOT);
    lv_obj_align(s_status, LV_ALIGN_BOTTOM_MID, 0, -15);

    s_welcome = box(s_root, 0, 0, 412, 412, ORANGE);
    lv_obj_t *welcome_brand = label(s_welcome, &lv_font_montserrat_16, WHITE, "MOSCEYE");
    lv_obj_set_style_text_letter_space(welcome_brand, 5, 0);
    lv_obj_align(welcome_brand, LV_ALIGN_TOP_MID, 0, 74);
    lv_obj_t *intro = label(s_welcome, &lv_font_montserrat_14, 0xffdfc8, "Una mirada a tu tienda");
    lv_obj_align(intro, LV_ALIGN_TOP_MID, 0, 269);
    emblem(s_welcome, 116, 122, 160);
    lv_obj_t *start = action(s_welcome, "EMPEZAR", start_cb);
    lv_obj_set_y(start, 310);
    retail_voice_init(s_root);
    lv_timer_create(poll_cb, 250, NULL);
    lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}

void retail_view_start(void)
{
    if (!s_root) return;
    if (!s_started) {
        /* A result already present on entry belongs to the previous visit. */
        char buf[4096];
        const char *path = getenv("MOSCEYE_STATUS_PATH");
        s_entry_request[0] = 0;
        if (read_json(path ? path : STATUS_PATH, buf, sizeof(buf)))
            get_string(buf, "request_id", s_entry_request, sizeof(s_entry_request));
    }
    s_started = true;
    lv_obj_add_flag(s_welcome, LV_OBJ_FLAG_HIDDEN);
    refresh();
}
void retail_view_set_visible(bool visible)
{
    if (!s_root) return;
    if (visible) {
        lv_obj_remove_flag(s_root, LV_OBJ_FLAG_HIDDEN);
        lv_obj_move_foreground(s_root);
        if (!s_started) lv_obj_remove_flag(s_welcome, LV_OBJ_FLAG_HIDDEN);
        refresh();
    } else {
        if (retail_voice_visible()) retail_voice_command("close");
        lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    }
}
bool retail_view_visible(void) { return s_root && !lv_obj_has_flag(s_root, LV_OBJ_FLAG_HIDDEN); }
void retail_view_toggle(void) { retail_view_set_visible(!retail_view_visible()); }
void retail_view_set_store_page(bool store)
{
    if (!s_pager) return;
    s_store_page = store;
    lv_obj_scroll_to_x(s_pager, store ? 412 : 0, LV_ANIM_OFF);
    update_dots();
    refresh();
}
