#include "contiki.h"
#include "cbor.h"
#include "dev/leds.h"
#include "dev/button-hal.h"
#include "coap-engine.h"
#include "sys/etimer.h"
#include "os/sys/log.h"
#include "model/vital_signs_panic.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#define LOG_MODULE "Sensor Node"
#define LOG_LEVEL LOG_LEVEL_INFO
#define SENSOR_NAME "snode_0"
#ifndef APPLICATION_CBOR
#define APPLICATION_CBOR 60
#endif
#define PANIC_THRESHOLD 0.50f
#define MAX_HR 110.0f
#define MIN_HR 50.0f
#define MAX_RR 30.0f
#define MIN_RR 8.0f
#define MAX_SPO2 100.0f
#define MIN_SPO2 85.0f
PROCESS(sensor_node, "Sensor Node");
AUTOSTART_PROCESSES(&sensor_node);


static clock_time_t interval=CLOCK_SECOND*30;
static int spo2=95;
static int respiration_rate=20;
static int heart_rate=70;
static bool panic_mode=false;
extern coap_resource_t vital_signs_resource;
static const float FEATURE_MEAN[3]  = { 76.1322f, 16.3496f, 96.5798f };
static const float FEATURE_SCALE[3] = { 5.4739f, 2.1311f, 1.3924f };

static void res_get_handler(coap_message_t *request, coap_message_t *response, uint8_t *buffer, uint16_t preferred_size, int32_t *offset){
    cbor_writer_state_t state;
    
    cbor_init_writer(&state, buffer, preferred_size);
/*
    cbor_open_map(&state);
        cbor_write_text(&state, "s", 1);
        cbor_write_unsigned(&state, spo2);
        
        cbor_write_text(&state, "r", 1);
        cbor_write_unsigned(&state, respiration_rate);
        
        cbor_write_text(&state, "h", 1);
        cbor_write_unsigned(&state, heart_rate);
    cbor_close_map(&state);*/

    cbor_open_map(&state);
        //base name
        cbor_write_text(&state, "bn", strlen("bn"));
        cbor_write_text(&state, SENSOR_NAME, strlen(SENSOR_NAME));
        //base time
//        cbor_write_text(&state, "bt", strlen("bt"));
//        cbor_write_unsigned(&state, clock_seconds());
        //array of vital signs
        cbor_write_text(&state, "e", strlen("e"));
        cbor_open_array(&state);
            //spo2
            cbor_open_map(&state);
                cbor_write_text(&state, "n", strlen("n"));
                cbor_write_text(&state, "spo2", strlen("spo2"));
                cbor_write_text(&state, "u", strlen("u"));
                cbor_write_text(&state, "%", strlen("%"));
                cbor_write_text(&state, "v", strlen("v"));
                cbor_write_unsigned(&state, spo2);
            cbor_close_map(&state);
            //respiration rate
            cbor_open_map(&state);
                cbor_write_text(&state, "n", strlen("n"));
                cbor_write_text(&state, "resRate", strlen("resRate"));
                cbor_write_text(&state, "u", strlen("u"));
                cbor_write_text(&state, "b/min", strlen("b/min"));
                cbor_write_text(&state, "v", strlen("v"));
                cbor_write_unsigned(&state, respiration_rate);
            cbor_close_map(&state);
            //heart rate
            cbor_open_map(&state);
                cbor_write_text(&state, "n", strlen("n"));
                cbor_write_text(&state, "heartRate", strlen("heartRate"));
                cbor_write_text(&state, "u", strlen("u"));
                cbor_write_text(&state, "bpm", strlen("bpm"));
                cbor_write_text(&state, "v", strlen("v"));
                cbor_write_unsigned(&state, heart_rate);
            cbor_close_map(&state);
        cbor_close_array(&state);
    cbor_close_map(&state);

    size_t len = cbor_end_writer(&state);
    coap_set_header_content_format(response, APPLICATION_CBOR);
    coap_set_payload(response, buffer, len);
    LOG_INFO("i have send:spo2: %d, Respiration Rate: %d, Heart Rate: %d\n sended in %zu byte", spo2, respiration_rate, heart_rate,len);

} 
//funtion to clamp the random values generated to a specific range to avoid data too high that the model never saw
static float clampf(float v,float low,float high){
    if(v<low){
        return low;
    }
    else if(v>high){
        return high;
    }
    return v;
}
//if we measure any critical signs we skip the model and immidiatly enter panic mode
static bool safety_override(float spo2,float respiration_rate,float heart_rate){
    if(heart_rate > 130 || heart_rate < 40 || respiration_rate > 30 || respiration_rate < 8 || spo2 < 88){
        LOG_INFO("safety override triggered, skipped model\n");
        return true;
    }
    return false;
}
static bool run_inference(int hr, int rr, int spo2){
    if(safety_override((float)spo2,(float)rr,(float)hr)){
        return true;
    }
    float clamped_hr=clampf((float)hr, MIN_HR, MAX_HR);
    float clamped_rr=clampf((float)rr, MIN_RR, MAX_RR);
    float clamped_spo2=clampf((float)spo2, MIN_SPO2, MAX_SPO2);
    
    float features[3];
    features[0]=(clamped_hr-FEATURE_MEAN[0])/FEATURE_SCALE[0];
    features[1]=(clamped_rr-FEATURE_MEAN[1])/FEATURE_SCALE[1];
    features[2]=(clamped_spo2-FEATURE_MEAN[2])/FEATURE_SCALE[2];
    float outputs[1]={0};
    eml_net_predict_proba(&vital_signs_panic, features,3,outputs,1);
    return outputs[0]>=PANIC_THRESHOLD;
}
static void exit_panic_mode(void){
    panic_mode=false;
    leds_off(LEDS_ALL);
    leds_on(LEDS_GREEN);
    interval=CLOCK_SECOND*30;
    LOG_INFO("Panic mode deactivated\n");
}
static void enter_panic_mode(void){
    panic_mode=true;
    leds_off(LEDS_ALL);
    leds_on(LEDS_RED);
    interval=CLOCK_SECOND*5;
    LOG_INFO("Panic mode activated\n");
}
static void button_press_handler(void){
    if(panic_mode){
        exit_panic_mode();
    }
    else if(!panic_mode){
        enter_panic_mode();
    }

}

static void res_event_handler(void){
    spo2 = 85 + (rand() % 14);       
    respiration_rate = 12 + (rand() % 20);
    heart_rate = 60 + (rand() % 90);
    if (run_inference(heart_rate,respiration_rate,spo2) && !panic_mode){
        enter_panic_mode();
    }
    coap_notify_observers(&vital_signs_resource);
    LOG_INFO("spo2: %d, Respiration Rate: %d, Heart Rate: %d\n", spo2, respiration_rate, heart_rate);
}
EVENT_RESOURCE(vital_signs_resource,
               "title=\"vital signs\";obs",
               res_get_handler,
               NULL,
               NULL,
               NULL,
               res_event_handler);
PROCESS_THREAD(sensor_node,ev,data){
        static struct etimer et;
        PROCESS_BEGIN();
        printf("%p\n",eml_error_str);
        printf("%p\n",eml_net_activation_function_strs);
        coap_activate_resource(&vital_signs_resource, "vital_signs");
        etimer_set(&et, interval);
	    leds_on(LEDS_GREEN);

        while(1){
            PROCESS_YIELD();
            if(ev==PROCESS_EVENT_TIMER&&data==&et){
                vital_signs_resource.trigger();
                etimer_set(&et, interval);
                LOG_INFO("Sensor Node is running\n");
            }
            else if(ev==button_hal_periodic_event){
                button_hal_button_t *btn = (button_hal_button_t *)data;
                if(btn->press_duration_seconds==5){
                    button_press_handler();
                    vital_signs_resource.trigger();
                    etimer_set(&et, interval);
                }
            }
            
        }
    PROCESS_END();
}


