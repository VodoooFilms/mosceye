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

#pragma once
#include <stdbool.h>
#include "lvgl.h"

/* Local voice draft. Sharing hands off to WhatsApp; it does not assert delivery. */
void retail_voice_init(lv_obj_t *parent);
void retail_voice_open(void);
bool retail_voice_visible(void);
void retail_voice_pointer_event(int x, int y, bool pressed);
void retail_voice_cleanup(void);
/* Scenario controls exercise the same handlers with SDL's dummy audio driver. */
bool retail_voice_command(const char *command);

#ifdef __APPLE__
int retail_voice_microphone_permission(void);
bool retail_voice_share_mac(const char *wav, char *error, unsigned error_size);
#endif
