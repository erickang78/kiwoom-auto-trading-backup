(()=>{
const source=document.querySelector('#panel-real .account-strip');
const target=document.querySelector('#panel-gold .intro > div');
const chip=source&&[...source.querySelectorAll('.account-chip')].find(el=>el.querySelector('b')?.textContent.trim()==='금현물계좌');
if(!chip||!target)return;
let strip=target.querySelector('.account-strip');
if(!strip){strip=document.createElement('div');strip.className='account-strip';target.append(strip)}
strip.append(chip);
})();
