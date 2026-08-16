#ifndef PROJECT_CONF_H_
#define PROJECT_CONF_H_

/* --- CONFIGURAZIONE SPECIFICA PER NRF52840 DONGLE --- */

/* 1. Abilita il supporto USB nativo nel kernel nRF52 */
#define USB_SERIAL_CONF_ENABLE      1

/* 2. Forza il protocollo SLIP (usato da tunslip6) a passare via USB */
#undef SLIP_ARCH_CONF_USB
#define SLIP_ARCH_CONF_USB          1

/* 3. Configurazione Border Router e Webserver */
#ifndef BORDER_ROUTER_CONF_WEBSERVER
#define BORDER_ROUTER_CONF_WEBSERVER 1
#endif

#if BORDER_ROUTER_CONF_WEBSERVER
#define UIP_CONF_TCP 1
#endif

/* 4. Aumenta i log per vedere cosa succede durante il debug */
//#define LOG_CONF_LEVEL_RPL                         LOG_LEVEL_DBG
//#define LOG_CONF_LEVEL_TCPIP                       LOG_LEVEL_DBG
//#define SLIP_CONF_LOG_LEVEL                        LOG_LEVEL_DBG
#undef LOG_CONF_LEVEL_ALL
#define LOG_CONF_LEVEL_ALL 0

#undef LOG_CONF_LEVEL_IPV6
#define LOG_CONF_LEVEL_IPV6 0

#undef LOG_CONF_LEVEL_RPL
#define LOG_CONF_LEVEL_RPL 0

#undef LOG_CONF_LEVEL_TCPIP
#define LOG_CONF_LEVEL_TCPIP 0

#undef LOG_CONF_LEVEL_6LOWPAN
#define LOG_CONF_LEVEL_6LOWPAN 0

#undef LOG_CONF_LEVEL_MAC
#define LOG_CONF_LEVEL_MAC 0

#endif /* PROJECT_CONF_H_ */
