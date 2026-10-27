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

#import <AppKit/AppKit.h>
#import <AVFoundation/AVFoundation.h>
#include "retail_voice.h"
#include <stdio.h>

int retail_voice_microphone_permission(void)
{
    AVAuthorizationStatus status = [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio];
    if (status == AVAuthorizationStatusAuthorized) return 1;
    if (status == AVAuthorizationStatusNotDetermined) {
        [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL granted) { (void)granted; }];
        return 0;
    }
    return -1;
}

bool retail_voice_share_mac(const char *wav, char *error, unsigned error_size)
{
    @autoreleasepool {
        /* Keep the shared copy alive after the draft and Charm are closed. */
        NSString *folder = [NSTemporaryDirectory() stringByAppendingPathComponent:
                            [@"mosceye-whatsapp-" stringByAppendingString:NSUUID.UUID.UUIDString]];
        NSFileManager *files = NSFileManager.defaultManager;
        NSError *failure = nil;
        if (![files createDirectoryAtPath:folder withIntermediateDirectories:NO
                              attributes:@{NSFilePosixPermissions: @0700} error:&failure]) {
            snprintf(error, error_size, "No se pudo preparar el audio. Reintenta."); return false;
        }
        NSString *output = [folder stringByAppendingPathComponent:@"Mensaje de voz.m4a"];
        NSTask *task = [[NSTask alloc] init];
        task.executableURL = [NSURL fileURLWithPath:@"/usr/bin/afconvert"];
        task.arguments = @[@"-f", @"m4af", @"-d", @"aac@44100", @"-b", @"64000",
                           [NSString stringWithUTF8String:wav], output];
        task.standardOutput = NSFileHandle.fileHandleWithNullDevice;
        task.standardError = NSFileHandle.fileHandleWithNullDevice;
        if (![task launchAndReturnError:&failure]) {
            [files removeItemAtPath:folder error:nil];
            snprintf(error, error_size, "No se pudo convertir el audio. Reintenta."); return false;
        }
        [task waitUntilExit];
        if (task.terminationStatus != 0) {
            [files removeItemAtPath:folder error:nil];
            snprintf(error, error_size, "No se pudo convertir el audio. Reintenta."); return false;
        }
        [files setAttributes:@{NSFilePosixPermissions: @0600} ofItemAtPath:output error:nil];
        NSPasteboard *clipboard = NSPasteboard.generalPasteboard;
        [clipboard clearContents];
        if (![clipboard writeObjects:@[[NSURL fileURLWithPath:output]]]) {
            [files removeItemAtPath:folder error:nil];
            snprintf(error, error_size, "No se pudo copiar. Vuelve a intentarlo."); return false;
        }
        NSWorkspace *workspace = NSWorkspace.sharedWorkspace;
        NSURL *url = [NSURL URLWithString:@"whatsapp://"];
        if (![workspace URLForApplicationToOpenURL:url]) url = [NSURL URLWithString:@"https://web.whatsapp.com/"];
        if (![workspace openURL:url]) {
            snprintf(error, error_size, "Audio copiado. Abre WhatsApp y pegalo alli."); return false;
        }
        return true;
    }
}
