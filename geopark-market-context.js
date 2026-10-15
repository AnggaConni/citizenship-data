(function(){
"use strict";
const CACHE_KEY="gpir:world-bank-context:v1";
const CACHE_TTL=12*60*60*1000;
const BASE="https://api.worldbank.org/v2";
const URLS={
 countries:BASE+"/country?format=json&per_page=400",
 gdp:BASE+"/country/all/indicator/NY.GDP.PCAP.CD?format=json&mrnev=1&per_page=20000",
 population:BASE+"/country/all/indicator/SP.POP.TOTL?format=json&mrnev=1&per_page=20000"
};
function validIso(code){return typeof code==="string"&&/^[A-Z]{3}$/.test(code);}
function readCache(){
 try{
  const item=JSON.parse(sessionStorage.getItem(CACHE_KEY)||"null");
  if(item&&Date.now()-item.cachedAt<CACHE_TTL&&item.payload&&item.payload.countries)return item.payload;
 }catch(_){}
 return null;
}
function writeCache(payload){
 try{sessionStorage.setItem(CACHE_KEY,JSON.stringify({cachedAt:Date.now(),payload}));}catch(_){}
}
async function requestRows(url){
 const response=await fetch(url,{headers:{Accept:"application/json"},cache:"force-cache"});
 if(!response.ok)throw new Error("World Bank HTTP "+response.status);
 const payload=await response.json();
 if(!Array.isArray(payload))throw new Error("Unexpected World Bank API response");
 return Array.isArray(payload[1])?payload[1]:[];
}
function latestValues(rows){
 const result={};
 for(const row of rows){
  const iso=String(row.countryiso3code||"").toUpperCase();
  const value=row.value==null?null:Number(row.value);
  const year=Number(row.date);
  if(!validIso(iso)||value==null||!Number.isFinite(value))continue;
  if(!result[iso]||year>Number(result[iso].year))result[iso]={value,year:Number.isFinite(year)?year:row.date};
 }
 return result;
}
async function load(options={}){
 if(!options.forceRefresh){
  const cached=readCache();
  if(cached)return {...cached,fromCache:true};
 }
 const responses=await Promise.allSettled([
  requestRows(URLS.countries),requestRows(URLS.gdp),requestRows(URLS.population)
 ]);
 const errors=[];
 const rows=responses.map((result,index)=>{
  if(result.status==="fulfilled")return result.value;
  errors.push(["countries","GDP per capita","population"][index]+": "+result.reason.message);
  return [];
 });
 const countries={};
 for(const row of rows[0]){
  const iso=String(row.iso3Code||"").toUpperCase();
  if(!validIso(iso))continue;
  countries[iso]={
   iso3:iso,name:row.name||iso,latitude:row.latitude==null?null:Number(row.latitude),
   longitude:row.longitude==null?null:Number(row.longitude),
   region:row.region&&row.region.value||null,income_level:row.incomeLevel&&row.incomeLevel.value||null
  };
 }
 const gdp=latestValues(rows[1]),population=latestValues(rows[2]);
 for(const [iso,row] of Object.entries(gdp)){
  countries[iso]=countries[iso]||{iso3:iso,name:iso,latitude:null,longitude:null,region:null,income_level:null};
  countries[iso].gdp_per_capita_usd=row.value;countries[iso].gdp_per_capita_year=row.year;
 }
 for(const [iso,row] of Object.entries(population)){
  countries[iso]=countries[iso]||{iso3:iso,name:iso,latitude:null,longitude:null,region:null,income_level:null};
  countries[iso].population=row.value;countries[iso].population_year=row.year;
 }
 const payload={source:"World Bank Indicators API v2",source_url:BASE+"/",retrieved_at:new Date().toISOString(),countries,warnings:errors};
 if(Object.keys(countries).length)writeCache(payload);
 return payload;
}
window.GPIRMarketContext={load};
})();