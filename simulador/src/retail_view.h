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

/*
 * Simulator-only retail overlay: a glanceable 412 x 412 checkout view fed by
 * /tmp/caja_status.json. It is not part of the production Muse UI and is never
 * compiled into firmware; it exists so a desktop preview can show retail data.
 */

/* Create the (hidden) overlay. Call once, after muse_ui_start(). */
void retail_view_init(void);

/* Enter the metric pages from the welcome screen. Does not trigger a check. */
void retail_view_start(void);

/* Simulate pressing CHEQUEAR (scenarios/tests). */
void retail_view_check(void);

/* Show or hide the overlay. */
void retail_view_set_visible(bool visible);
bool retail_view_visible(void);
void retail_view_toggle(void);

/* Select the queue or visible-people page without starting another inference. */
void retail_view_set_store_page(bool store);

/* Raw simulator pointer events retain fast drags between LVGL polling ticks. */
void retail_view_pointer_event(int x, int y, bool pressed);
