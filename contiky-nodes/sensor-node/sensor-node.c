#include "contiki.h"
#include "coap-engine.h"
#include "sys/etimer.h"
#include "os/sys/log.h"
#include <stdio.h>
#include <stdlib.h>
#define LOG_MODULE "Sensor Node"
#define LOG_LEVEL LOG_LEVEL_INFO
PROCESS(sensor_node, "Sensor Node");
AUTOSTART_PROCESSES(&sensor_node);


static clock_time_t interval=CLOCK_SECOND*5;
static int spo2=95;
static int respiration_rate=20;
static int heart_rate=70;
static void res_event_handler(void){
    spo2 = 85 + (rand() % 14);       
    respiration_rate = 12 + (rand() % 20);
    heart_rate = 60 + (rand() % 90);
    LOG_INFO("spo2: %d, Respiration Rate: %d, Heart Rate: %d\n", spo2, respiration_rate, heart_rate);
}
PROCESS_THREAD(sensor_node,ev,data){
        static struct etimer et;
        PROCESS_BEGIN();
        etimer_set(&et, interval);
        while(1){
            PROCESS_WAIT_EVENT_UNTIL(etimer_expired(&et));
            etimer_reset(&et);
            res_event_handler();
            LOG_INFO("Sensor Node is running\n");
        }
    
    PROCESS_END();
}
