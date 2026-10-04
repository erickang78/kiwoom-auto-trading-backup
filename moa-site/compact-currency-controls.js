(()=>{
'use strict';
const style=document.createElement('style');style.textContent=`
#holdings-currency-toggle{display:none!important}
#panel-real .intro.currency-intro .currency-control,#panel-quote .intro.currency-intro .currency-control,#panel-trade #order-currency{width:72px;height:30px;padding:3px;border-radius:10px;flex-basis:72px}
#panel-real .intro.currency-intro .currency-control label,#panel-real .intro.currency-intro .currency-control span,#panel-quote .intro.currency-intro .currency-control label,#panel-quote .intro.currency-intro .currency-control span,#panel-trade #order-currency [data-order-currency]{height:24px}
#panel-real .intro.currency-intro .currency-control span,#panel-quote .intro.currency-intro .currency-control span,#panel-trade #order-currency [data-order-currency]{font-size:14px;border-radius:7px}
#panel-real .intro.currency-intro .currency-toggle-button,#panel-quote .intro.currency-intro .currency-toggle-button,#panel-trade #order-currency .order-currency-toggle{border-radius:10px}
`;document.head.append(style);
})();
