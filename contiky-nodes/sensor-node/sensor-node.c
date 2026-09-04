#include "contiki.h"
#include "cbor.h"
#include "dev/leds.h"
#include "dev/button-hal.h"
#include "coap-engine.h"
#include "sys/etimer.h"
#include "coap-blocking-api.h"
#include "os/sys/log.h"
#include "model/vital_signs_panic.h"
#include <string.h>
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
#define DOUBLE_PRESS_INTERVAL (CLOCK_SECOND/2)
#define PYTHON_APP_URI "coap://[fd00::1]"
#define MAX_BUFFERED_READINGS 5
PROCESS(sensor_node, "Sensor Node");
PROCESS(ping_client_process, "Ping Client Process");
AUTOSTART_PROCESSES(&sensor_node);

typedef struct{
    int hr;
    int rr;
    int spo2;
}vital_data_t;

// Global variables
static bool ping_started=false;
static vital_data_t data_buffer[MAX_BUFFERED_READINGS];
static int buffer_count=0;
static int head=0;
static int tail=0;
static bool network_connected=true;
static clock_time_t ping_interval=CLOCK_SECOND*30;
static clock_time_t interval=CLOCK_SECOND*30;
static struct etimer blink_et;
static int spo2=95;
static int respiration_rate=20;
static int heart_rate=70;
static bool panic_mode=false;
//static bool edge_ai_test_mode=false;
typedef enum{
    PATIENT_STABLE,
    PATIENT_CRITICAL,
    PATIENT_DANGER,
}patient_test_status_t;

static patient_test_status_t test_status=PATIENT_STABLE;

extern coap_resource_t vital_signs_resource;
static const float FEATURE_MEAN[3]  = {76.1263f, 16.3470f, 96.5792f};  /* heart_rate  respiratory_rate  oxygen_saturation */
static const float FEATURE_SCALE[3] = {5.4737f, 2.1339f, 1.3945f};
static clock_time_t last_release_time=0;

static void ping_chunk_handler(coap_message_t *response){
    if(response==NULL){
        if(network_connected){
            network_connected=false;
            ping_interval=CLOCK_SECOND*5;
            LOG_INFO("[NETWORK]no answer from heartbeat server unreachable or timeout \n");
        }
    }
    else{
        if(!network_connected){
            network_connected=true;
            ping_interval=CLOCK_SECOND*30;
            coap_notify_observers(&vital_signs_resource);
            LOG_INFO("[NETWORK]server reachable emptying buffer \n");
        }
    }
}

static void res_get_handler(coap_message_t *request, coap_message_t *response, uint8_t *buffer, uint16_t preferred_size, int32_t *offset){
    if(!ping_started) {
        uint32_t observe = 0;
        if(coap_get_header_observe(request, &observe) && observe == 0) {
            ping_started = true;
            process_start(&ping_client_process, NULL);
            LOG_INFO("[NETWORK] observer connected, started ping\n");
        }
    }
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
        cbor_write_text(&state, "int", strlen("int"));
        cbor_write_unsigned(&state, interval / CLOCK_SECOND);
        //base time
//        cbor_write_text(&state, "bt", strlen("bt"));
//        cbor_write_unsigned(&state, clock_seconds());
        //array of vital signs
        cbor_write_text(&state, "e", strlen("e"));
        cbor_open_array(&state);
        if(buffer_count==0){
            data_buffer[0].hr=heart_rate;
            data_buffer[0].rr=respiration_rate;
            data_buffer[0].spo2=spo2;
            buffer_count=1;
        }
        int current_idx=tail;
        for(int i=0;i<buffer_count;i++){
            //spo2
            cbor_open_map(&state);
                cbor_write_text(&state, "n", strlen("n"));
                cbor_write_text(&state, "spo2", strlen("spo2"));
                cbor_write_text(&state, "u", strlen("u"));
                cbor_write_text(&state, "%", strlen("%"));
                cbor_write_text(&state, "v", strlen("v"));
                cbor_write_unsigned(&state, data_buffer[current_idx].spo2);
            cbor_close_map(&state);
            //respiration rate
            cbor_open_map(&state);
                cbor_write_text(&state, "n", strlen("n"));
                cbor_write_text(&state, "resRate", strlen("resRate"));
                cbor_write_text(&state, "u", strlen("u"));
                cbor_write_text(&state, "b/min", strlen("b/min"));
                cbor_write_text(&state, "v", strlen("v"));
                cbor_write_unsigned(&state, data_buffer[current_idx].rr);
            cbor_close_map(&state);
            //heart rate
            cbor_open_map(&state);
                cbor_write_text(&state, "n", strlen("n"));
                cbor_write_text(&state, "heartRate", strlen("heartRate"));
                cbor_write_text(&state, "u", strlen("u"));
                cbor_write_text(&state, "bpm", strlen("bpm"));
                cbor_write_text(&state, "v", strlen("v"));
                cbor_write_unsigned(&state, data_buffer[current_idx].hr);
            cbor_close_map(&state);
            current_idx=(current_idx+1)%MAX_BUFFERED_READINGS;
        }
        buffer_count=0;
        head=0;
        tail=0;
        cbor_close_array(&state);
    cbor_close_map(&state);

    size_t len = cbor_end_writer(&state);
    coap_set_header_content_format(response, APPLICATION_CBOR);
    coap_set_payload(response, buffer, len);
    LOG_INFO("i have send:spo2: %d, Respiration Rate: %d, Heart Rate: %d sended in %zu byte\n", spo2, respiration_rate, heart_rate,len);

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
    float proba=vital_signs_panic_regress1(features,3);
    int printable_output=(int)(proba * 1000.0f);
    LOG_INFO("Model output: %d.%03d\n", printable_output/1000, printable_output%1000);
    return proba>=PANIC_THRESHOLD;
}
static void exit_panic_mode(void){
    panic_mode=false;
    leds_off(LEDS_ALL);
    if(test_status==PATIENT_CRITICAL){
        leds_single_on(LEDS_YELLOW);
    }
    leds_on(LEDS_GREEN);
    interval=CLOCK_SECOND*30;
    LOG_INFO("Panic mode deactivated\n");
}
static void enter_panic_mode(void){
    panic_mode=true;
    leds_off(LEDS_ALL);
    if(test_status==PATIENT_CRITICAL){
        leds_single_on(LEDS_YELLOW);
    }
    leds_on(LEDS_RED);
    interval=CLOCK_SECOND*5;
    LOG_INFO("Panic mode activated\n");
}
static void res_put_handler(coap_message_t *request, coap_message_t *response,uint8_t *buffer, uint16_t preferred_size, int32_t *offset){
  const uint8_t *payload=NULL;
  int len=coap_get_payload(request, &payload);
  if(len>0){
    if(strncmp((const char*)payload,"0",1)==0){
        if(panic_mode){
            exit_panic_mode();
        }
    }
    else if(strncmp((const char*)payload,"1",1)==0){
        if(!panic_mode){
            enter_panic_mode();
        }
    }
    coap_set_status_code(response,CHANGED_2_04);
  }
  else{
    coap_set_status_code(response,BAD_REQUEST_4_00);
  }  
}
static void button_press_handler(void){
    if(panic_mode){
        exit_panic_mode();
    }
    else if(!panic_mode){
        enter_panic_mode();
    }

}
static void double_button_press_handler(void){
    switch(test_status){
        case PATIENT_STABLE:
            test_status=PATIENT_CRITICAL;
            leds_single_on(LEDS_YELLOW);
            LOG_INFO("switching to critical status for patient\n");
            break;
        case PATIENT_CRITICAL:
            test_status=PATIENT_DANGER;
            LOG_INFO("switching to danger status for patient\n");
            process_post(&sensor_node,PROCESS_EVENT_TIMER,&blink_et);
            etimer_set(&blink_et,CLOCK_SECOND/2);
            break;
        case PATIENT_DANGER:
            test_status=PATIENT_STABLE;
            leds_single_off(LEDS_YELLOW);
            LOG_INFO("switching to stable status for patient\n");
            break;
        default:
            LOG_INFO("status not recognised");    
    }
}
static void res_event_handler(void){
    switch(test_status){
        case PATIENT_DANGER:
            spo2 = 75 + (rand() % 10);             
            respiration_rate = 32 + (rand() % 8);  
            heart_rate = 135 + (rand() % 20);
            break;
        case PATIENT_CRITICAL:
            spo2 = 80 + (rand() % 16);               
            respiration_rate = 15 + (rand() % 20);  
            heart_rate = 75 + (rand() % 80);
            break;
        case PATIENT_STABLE:
            spo2 = 94 + (rand() % 6);              
            respiration_rate = 12 + (rand() % 9);  
            heart_rate = 60 + (rand() % 31);
            break;
        default:
            LOG_INFO("unknown status\n");

    }
    if (run_inference(heart_rate,respiration_rate,spo2) && !panic_mode){
        enter_panic_mode();
    }
    data_buffer[head].hr=heart_rate;
    data_buffer[head].rr=respiration_rate;
    data_buffer[head].spo2=spo2;
    head = (head+1)%MAX_BUFFERED_READINGS;
    if(buffer_count<MAX_BUFFERED_READINGS){
        buffer_count++;
    }
    else{
        tail=(tail+1)%MAX_BUFFERED_READINGS;
    }
    if(network_connected){
        coap_notify_observers(&vital_signs_resource);

    }
    else{
        LOG_INFO("[NETWORK]server unreachable, buffering data\n");
    }
    LOG_INFO("spo2: %d, Respiration Rate: %d, Heart Rate: %d\n", spo2, respiration_rate, heart_rate);
}
EVENT_RESOURCE(vital_signs_resource,
               "title=\"vital signs\";obs",
               res_get_handler,
               NULL,
               res_put_handler,
               NULL,
               res_event_handler);

PROCESS_THREAD(ping_client_process, ev, data) {
  static struct etimer ping_timer;
  static coap_endpoint_t server_ep;
  static coap_message_t request[1];

  PROCESS_BEGIN();
  coap_endpoint_parse(PYTHON_APP_URI, strlen(PYTHON_APP_URI), &server_ep);
  etimer_set(&ping_timer, ping_interval);
  while(1) {
    PROCESS_WAIT_EVENT_UNTIL(etimer_expired(&ping_timer));
    coap_init_message(request, COAP_TYPE_CON, COAP_POST, 0);
    coap_set_header_uri_path(request, "ping");
    coap_set_payload(request, (uint8_t *)SENSOR_NAME, strlen(SENSOR_NAME));
    COAP_BLOCKING_REQUEST(&server_ep, request, ping_chunk_handler);
    etimer_set(&ping_timer, ping_interval);
  }
  PROCESS_END();
}



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
            if(ev==PROCESS_EVENT_TIMER){
                if(data==&et){
                    vital_signs_resource.trigger();
                    etimer_set(&et, interval);
                    LOG_INFO("Sensor Node is running\n");
                }
                else if(data==&blink_et){
                    if(test_status==PATIENT_DANGER){
                        leds_single_toggle(LEDS_YELLOW);
                        etimer_reset(&blink_et);
                    }
                }
                
            }
            else if(ev==button_hal_periodic_event){
                button_hal_button_t *btn = (button_hal_button_t *)data;
                if(btn->press_duration_seconds==5){
                    button_press_handler();
                    vital_signs_resource.trigger();
                    etimer_set(&et, interval);
                }
            }
            else if(ev==button_hal_release_event){
                button_hal_button_t *btn=(button_hal_button_t *)data;
                if(btn->press_duration_seconds<1){
                    clock_time_t now=clock_time();
                    if(now-last_release_time<=DOUBLE_PRESS_INTERVAL){
                        double_button_press_handler();
                        last_release_time=0;
                    }
                    else{
                    last_release_time=now;
                }
                }
                
            }
            
        }
    PROCESS_END();
}






